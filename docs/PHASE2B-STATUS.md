# Phase 2b status — what is done, what is proven, what is not

Written after the Phase 2 review that rejected starting Phase 3. Every line here
is either a command you can re-run or an explicit "not done".

## How to read the labels

| Label | Means |
| --- | --- |
| **DONE** | The code exists and is committed. No claim beyond that. |
| **VERIFIED (fakes)** | A test in `backend/tests/` exercises it against in-memory fakes (`MemoryAuthStore`, `FakeAuth`, `RecordingMailer`). Re-run: `pytest -q`. |
| **VERIFIED (scratch Postgres)** | `supabase/tests/run_migration_checks.py` applied every migration to a real Postgres with a **stubbed** `auth` schema. Re-run: `python supabase/tests/run_migration_checks.py`. This proves the SQL, not Supabase's behaviour. |
| **VERIFIED (local Supabase)** | The Supabase CLI stack: real GoTrue, real `auth.uid()`, real JWT-based RLS. Re-run in CI (`supabase-local-stack` job) or locally with the commands at the end. |
| **VERIFIED (staging)** | A hosted project. **Still BLOCKED** — no URL/keys exist. |
| **NOT VERIFIED** | Implemented or plausible, but nothing ran that proves it. |
| **NOT DONE** | Not implemented. |
| **BLOCKED** | Cannot proceed without something only a human can supply. |

The 18 `xfail`s are unchanged and all belong to `tests/test_search_ranking.py`
(ranking defects on common words: heart→中心, eye→额叶, hot→热门, teacher→先生,
phone→跑分, beautiful→那). None is auth-related; the reasons are pinned in
`docs/RANKING_KNOWN_DEFECTS.md`.

## 1. The ten Phase 2b items

| # | Item | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Sessions owned by FastAPI: family id, `last_seen`, absolute expiry, enforced on every request; `GET /auth/sessions`; `logout-all`; idle 7 d; absolute 30 d | **DONE**, **VERIFIED (fakes)**, **VERIFIED (scratch Postgres)** for the table | `backend/app/services/sessions.py`; `GET/POST/DELETE` in `backend/app/api/v1/auth.py`; migration `20261115090000_auth_06_sessions.sql` + its down file; tests `test_session_list_shows_this_device_without_identifiers`, `test_logout_all_kills_every_device_immediately`, `test_idle_session_is_retired`, `test_absolute_expiry_retires_an_active_session`, `test_revoking_one_device_leaves_the_other_signed_in`, `test_a_user_cannot_revoke_someone_elses_session`; runner now reports 22 checks |
| 1b | Does the free Supabase plan support session time-boxing / inactivity timeout? | **NOT VERIFIED** — and no longer load-bearing | Supabase's docs are not in this repo and the free plan's feature list was not fetched from the dashboard. Rather than depend on an unverified paid feature, the two clocks are enforced in `sessions.enforce()`, which runs on **every** authenticated request (A30) |
| 2 | Password reset **and** password change revoke all sessions | **DONE**, **VERIFIED (fakes)** | New endpoint `POST /auth/password/change` (requires the current password, 403 without it); tests `test_password_reset_revokes_every_session`, `test_password_change_revokes_every_session`, `test_password_change_requires_the_current_password`, `test_password_change_applies_the_password_policy` |
| 3 | Disposable-email blocklist: maintained list, licence noted, update script, manual allow override, tests | **DONE**, **VERIFIED (fakes)** | `backend/app/services/disposable_domains.py`; seed list of 340 domains (`backend/data/disposable_email_seed.txt`); `backend/tools/update_disposable_domains.py` fetches 10,181 domains; override `AUTH_DISPOSABLE_ALLOW_DOMAINS`; tests `test_register_start_refuses_a_disposable_domain`, `…subdomain…`, `test_allow_override_unblocks_a_false_positive`, `test_ordinary_domains_are_not_blocked`. **Licence: upstream reports `NOASSERTION` ("Other")**, so the generated list is git-ignored and never redistributed (see `backend/data/DISPOSABLE-LICENSE.txt` after running the script) |
| 4 | AI endpoints: Option B — guest allowance keyed by IP + install id, larger per-user allowance, global budget, no `X-Client-Id` bucketing, IPv6 /64 | **DONE**, **VERIFIED (fakes)** | `backend/app/core/ai_guard.py` `_identity_buckets()`; a valid bearer token → `user:<uid>`; otherwise `guest:<ip bucket>:<install hash>` **and** `guest-net:<ip bucket>` with a multiplier, so rotating the header buys one bucket, not unlimited quota; IPv6 collapsed to /64; tests in `test_ai_phase6_hardening.py` (`test_ipv6_is_counted_per_64_not_per_address`, `test_rotating_the_install_id_still_hits_the_network_bucket`, `test_a_valid_token_moves_the_caller_to_the_user_budget`) |
| 5 | Dedicated tests: login by username **and** email, pending account cannot log in, dummy-hash path runs, register/complete ACTIVE-only + reserved names + username policy, `nepali_enabled` | **DONE**, **VERIFIED (fakes)** | `backend/tests/test_auth_phase2b.py`: `test_login_by_username_and_by_email_both_succeed`, `test_a_pending_account_cannot_log_in`, `test_an_unknown_username_still_makes_one_upstream_call`, `test_complete_creates_an_active_profile_only_there`, `test_reserved_usernames_are_refused` (3 params), `test_username_policy_is_enforced` (3 params), `test_nepali_enabled_is_visible_and_not_settable_by_patch` |
| 5b | Login timing equality against a **real** backend | **NOT VERIFIED** | With a fake upstream there is no network latency to compare. What is proven is that an unknown identifier still performs exactly one password grant (`test_an_unknown_username_still_makes_one_upstream_call`) |
| 6 | Supabase CLI local stack in CI; label results "VERIFIED (local Supabase)" | **VERIFIED (local Supabase)** — job green on `affc86c`, 12 checks passed | `.github/workflows/contracts.yml` job `supabase-local-stack`; `supabase/config.toml` (public sign-up off); `supabase/tests/run_local_stack_checks.py` asserts anon cannot read profiles, a real JWT sees only its own row, cross-user read fails, refresh rotates and a replayed refresh token fails after 12 s, and (when the DB port is reachable) that pg_cron is present and the purge job is scheduled. Two findings: the CLI stack ships without pg_cron (schedule stays **NOT VERIFIED**), and GoTrue still exchanges a replayed refresh token after 40 s, so refresh-reuse revocation is ours, not Supabase's (A30) |
| 7 | Status table against every item of Prompts A, B, C | **DONE** | Section 2 below |
| 8 | What behaviour was removed with the old Supabase client | **DONE** | Section 3 below |
| 9 | Deletion also removes challenges/signup tokens; `details_json`/`endpoint` hold no identifiers; blocklist rows for a deleted user; update A29 | **DONE** for the code, **DONE** for the audit | Section 4 below; `test_deletion_removes_challenges_and_signup_tokens`; A29 extended |
| 10 | Phase 4 reminder (refresh token in `flutter_secure_storage`), PR #2 targets `auth-system`, no merge to main | **DONE** (recorded) | Section 5 below, `docs/HUMAN_TODO.md` §18 |

Test totals after this round: **594 passed, 18 xfailed** (`python -m pytest -q`),
**22 passed, 0 failed** for the migration checks.

## 2. Every Prompt A / B / C item

Legend: A = product/auth behaviour, B = security, C = delivery/verification.

| Item | Prompt | Status | Where / why |
| --- | --- | --- | --- |
| Email → 6-digit code → username + password signup, ACTIVE only at completion | A | **VERIFIED (fakes)** | `register_start/verify/complete`, `test_complete_creates_an_active_profile_only_there` |
| Login by username **or** email, one message for every failure | A | **VERIFIED (fakes)** | `test_login_by_username_and_by_email_both_succeed`, `test_a_pending_account_cannot_log_in` |
| Forgot / reset password by code | A | **VERIFIED (fakes)** | `test_password_reset_revokes_every_session` |
| Change password while signed in | A | **VERIFIED (fakes)** | `POST /auth/password/change` |
| Username availability, case-insensitive, no shape leak | A | **VERIFIED (fakes)** | `test_username_available_case_insensitive_…` in `test_auth_phase2.py` |
| Reserved usernames refused | A | **VERIFIED (fakes)** | `profiles.is_reserved()` mirrors `reserved_usernames` (migration 04); 3-param test |
| Username policy (length, characters, no confusable unicode) | A | **VERIFIED (fakes)** | `test_username_policy_is_enforced` |
| `nepali_enabled` default at signup, visible in profile, not settable by PATCH | A | **VERIFIED (fakes)** | `test_nepali_enabled_is_visible_and_not_settable_by_patch` |
| `nepali_enabled` cached **locally** so offline lookup keeps the user's language | A | **NOT DONE** | No client cache yet: the value is read from the profile on each online request. Phase 4, with the same store as the token |
| Offline dictionary lookup never requires login | A | **DONE** (by design) | `/search` and the bundled SQLite are unauthenticated; no route gates the dictionary. Not re-tested this round |
| Logout clears tokens only; favorites/history stay | A | **NOT DONE** (UI) | `favorites_repository.clear()` exists and says it is only for the explicit wipe; there is no account UI yet to call either |
| Explicit "Log out and clear local data" | A | **NOT DONE** (UI) | Phase 4, with the signed-in account screen |
| In-app account deletion with re-authentication | A | **VERIFIED (fakes)** | `DELETE /auth/account` requires password or code; 403 otherwise |
| Static Play account-deletion page | A | **NOT DONE** | Deliberately deferred (A21); no web client in v1 |
| Mobile-only contract (no cookie/CSRF rules) | A | **DONE** | `docs/auth-contract.yaml`: `removed_from_v1` lists the web cookie/CSRF pair; every auth route is bearer |
| Device install id in secure storage, not hardware ids | A | **NOT DONE** | Phase 4 (`flutter_secure_storage`); no id is collected today |
| `allowBackup=false` + full backup rules | A | **DONE** | `android/app/src/main/AndroidManifest.xml`, `res/xml/data_extraction_rules.xml` (all domains excluded from cloud backup and device transfer) |
| `FLAG_SECURE` (no screenshots / recents preview) | A | **DONE** | `MainActivity.kt` sets the flag in `onCreate` |
| Biometric lock option | A | **NOT DONE** | Needs `local_auth` + a settings toggle; Phase 4 |
| Google sign-in removed (code, dependency, client ids) | A | **DONE** | A22; no `google_sign_in` in `pubspec.yaml`, no provider config |
| The app talks only to FastAPI; no Supabase key in the APK | B | **DONE** | `pubspec.yaml` has no `supabase_flutter`; `lib/core/supabase_config.dart` deleted; `flutter pub get`/`analyze`/`test` pass without it |
| FastAPI owns the code; only hashes stored, expiry + attempt counter | B | **VERIFIED (fakes)** | `otp.py` HMAC + pepper, `test_auth_phase2.py` (64-hex hash stored, 5 attempts, cooldown) |
| Signup token is opaque and stored hashed | B | **VERIFIED (fakes)** | `auth_signup_tokens` stores the hash; `token_urlsafe(32)` |
| Per-address send cap cannot block the real owner | B | **VERIFIED (fakes)** | valid unexpired code always verifies; per-IP bucket does the heavy lifting |
| Pre-account takeover impossible (no password set before verification) | B | **VERIFIED (fakes)** | nothing is written to `profiles` before `register/complete` |
| 422 never echoes input; `extra="forbid"` everywhere; StatusModel | B | **VERIFIED (fakes)** | `safe_validation_handler` drops `input`/`ctx`; `StrictModel` forbids extras |
| No code / password / token in logs or stdout | B | **VERIFIED (fakes)** | `obs.log_event` allow-list drops unknown fields; the mailer is injected in tests, never printed |
| OTP pepper only in env, never DB or git | B | **DONE** | `AUTH_CODE_PEPPER` required ≥16 chars, else 503; `.env.example` empty; gitleaks clean |
| HIBP check, fail open | B | **VERIFIED (fakes)** | `test_passwords.py` |
| Disposable-domain blocklist + override | B | **VERIFIED (fakes)** | section 1 item 3 |
| Trusted proxy: `X-Forwarded-For` only from `TRUSTED_PROXIES`, rightmost non-trusted hop | B | **VERIFIED (fakes)** | `backend/app/core/net.py`, `test_net.py` (spoofed header ignored, multi-hop, garbage fallback) |
| Country from Cloudflare header / GeoIP, country only, never the IP | B | **VERIFIED (fakes)** | `net.country_code()`; two-letter code only, trusted peer only |
| IP rate limits use the resolved client IP, IPv6 /64 | B | **DONE** for AI quota; **NOT DONE** for auth endpoints | `ai_guard` buckets by /64; the auth rate-limit tables exist but nothing calls `client_ip` yet — that is Phase 3 work, as the review said |
| Sessions: list, logout-all, revoke one, idle + absolute clocks | B | **VERIFIED (fakes)** | section 1 item 1 |
| Reset and change revoke every session | B | **VERIFIED (fakes)** | section 1 item 2 |
| Delete requires re-authentication | B | **VERIFIED (fakes)** | `403` without a correct password/code |
| `security_events` anonymised on deletion (`user_id`, `device_id`, `ip_hash`) | B | **DONE** + **VERIFIED (fakes)** | `anonymize_events` clears all three; A29 |
| Blocklist rows for a deleted user | B | **DONE** (policy) | Section 4 |
| Turnstile | B | **NOT DONE** | Phase 3, explicitly after 2b |
| Security events persisted to Postgres | B | **NOT DONE** | Phase 3; today `obs` writes stdout only |
| Upload validation / security agent | B | **NOT DONE** | Phase 3 |
| Migrations apply cleanly, 22 checks, down migrations, up→down→up | C | **VERIFIED (scratch Postgres)** | `run_migration_checks.py`; `supabase/rollback/*` |
| Real RLS with a real JWT | C | **VERIFIED (local Supabase)** | `run_local_stack_checks.py` in CI: anon sees nothing, a real JWT sees only its own row, a cross-user read by id fails |
| pg_cron schedule on the real project | C | **NOT VERIFIED** | local stack check exists; a hosted plan is needed for the real schedule |
| Hosted staging run | C | **BLOCKED** | no URL/anon key/service-role key/secret (A23) |
| Full-history secret scan | C | **VERIFIED (local)** | gitleaks 8.30.1, full history, 0 findings; allowlist pinned to one commit + one path + one literal |
| PR discipline (auth-system only, no merge to main) | C | **DONE** | PR #2 targets `auth-system`; nothing is merged to `main`; no release cut from this branch |
| Run on a real phone | C | **DONE** — Samsung SM-M166P (Android 16, API 36), debug APK | Installed over USB, launched, dictionary copied (99 MB in `files/`), no Flutter exception in logcat, `FLAG_SECURE` confirmed by the phone returning a black screenshot. Detail in section 6 |

## 3. What was removed with the old Supabase client

Commit `f9cae05`. Deleted files:

- `lib/core/supabase_config.dart` — the URL + anon key constants. The values were
  empty; that does **not** prove no earlier build injected them (`--dart-define`
  could have), which is why `HUMAN_TODO` #15 still says "if any build shipped a
  key, rotate it".
- `lib/data/auth_provider.dart` — the client-side session holder: sign-up,
  sign-in, sign-out, `currentSession`, `onAuthStateChange`, token refresh.
- `lib/data/models/auth_state.dart`, `lib/data/models/signed_in_user.dart` —
  the client's own view of "who is signed in" and their profile fields.

Behaviour that changed as a result:

1. **No client-side authentication at all.** The account screen is a placeholder;
   nothing can sign in until Phase 4 wires the FastAPI flow (email → code →
   username/password).
2. **No client-side token refresh.** `authTokenProvider` holds an access token in
   memory only; after a restart the user is effectively signed out. The 30-day
   server session exists but the client cannot use it until the refresh token is
   stored in `flutter_secure_storage` (Phase 4).
3. **Favorites became local-only.** `favorites_repository` previously merged the
   local SQLite rows with rows read from Supabase; now it is pure local and has a
   `clear()` used only by the explicit "log out and clear local data" action.
   Any Supabase-side favorites from an earlier test build are no longer read —
   there is no sync in v1 (A28).
4. **Settings' account entry is inert.** It shows "Not open yet" instead of a
   signed-in identity, because there is no identity to show.
5. **`supabase_flutter` dropped from `pubspec.yaml`**, so the platform plugin
   registrants and `pubspec.lock` changed too. The APK can no longer reach
   Supabase Auth directly, which is the point (A24).
6. **No push of auth events from the app.** The old provider reacted to
   `onAuthStateChange`; that path no longer exists, so the app cannot silently
   refresh or sign out on its own.
7. **Corrections / history sync**: nothing in the current app wrote corrections
   through the Supabase client, so nothing was lost there; history was and
   remains local.

## 4. Deletion: what else was checked

- **Challenges and signup tokens are removed.** `delete_account` reads the
  profile's e-mail before deleting, then calls `store.purge_identity_traces(email,
  email_hash)`, which deletes `auth_challenges where email_hash = …` and
  `auth_signup_tokens where email = …`. Test:
  `test_deletion_removes_challenges_and_signup_tokens`.
- **`security_events.endpoint`** holds only static route names (`"/auth/account"`),
  never a path parameter; `"/auth/sessions/{id}"` is logged as a literal template,
  not the id.
- **`security_events.details_json`** is not written by today's `obs.log_event` at
  all: it accepts only an allow-list of scalar fields (`event`, `status`, `count`,
  `reason`, …) and drops anything else, so no identifier can reach that column
  (A13). When Phase 3 starts persisting events, the allow-list is the guard.
- **`blocklist` rows** are keyed `(kind, value_hash)` with no `user_id`, so a
  deleted account leaves no join to a person. Policy: rows are **kept** after
  deletion — they are abuse controls, not account data; the hash must be salted
  with a secret pepper when Phase 3 starts writing them, or it becomes a
  guessable pseudonym. No rows exist today.
- **A29 updated** with these three points and with the note that backups and
  Resend's own logs keep data for a while, which the privacy policy must say.

## 5. Phase 4 reminders (recorded, not implemented)

1. Store the refresh token in `flutter_secure_storage`; an in-memory token
   makes the 30-day session meaningless after an app restart.
2. Cache `nepali_enabled` locally so offline lookup keeps the user's language.
3. Build the account screen: sign-in, session list, "sign out this device",
   "log out all devices", "log out and clear local data", delete account.
4. Add a biometric-lock option (`local_auth`).
5. PR #2 keeps targeting `auth-system`; do not merge to `main`, do not release
   from this branch while the account screen is a placeholder.

## 6. Run it yourself

```powershell
# backend (from backend/)
.\.venv\Scripts\python.exe -m pytest -q                    # 594 passed, 18 xfailed

# migrations (from the repo root)
backend\.venv\Scripts\python.exe supabase\tests\run_migration_checks.py   # 22 passed

# full-history secret scan (needs git on PATH)
gitleaks git --no-banner --redact -c .gitleaks.toml -f json -r gl.json --log-level error .

# local Supabase stack (needs Docker + the Supabase CLI)
supabase start
supabase db reset --local
supabase status -o env > sb.env      # then export API_URL / ANON_KEY / SERVICE_ROLE_KEY
backend\.venv\Scripts\python.exe supabase\tests\run_local_stack_checks.py

# disposable list (deploy-time artifact, not committed)
backend\.venv\Scripts\python.exe backend\tools\update_disposable_domains.py
```

## 7. Run on the phone

Device: Samsung **SM-M166P**, Android 16 (API 36). Debug APK, backend reached over USB
(`adb reverse tcp:8000 tcp:8000`, so the app's default `http://127.0.0.1:8000` lands on the
PC's FastAPI without either device sharing a network).

```powershell
# once: Windows Developer Mode must be ON, or `flutter pub get` dies creating plugin symlinks
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" `
  -Name AllowDevelopmentWithoutDevLicense -Value 1 -Type DWord

& "C:\flutter\bin\flutter.bat" build apk --debug
adb install -r build\app\outputs\flutter-apk\app-debug.apk
adb reverse tcp:8000 tcp:8000
adb shell am start -n com.example.trilingual_dictionary/.MainActivity
```

Evidence collected:

* the activity is in focus (`mCurrentFocus`), process alive, no Flutter exception in `logcat`
  (only Samsung `mali_gralloc` noise, which every Flutter app on this GPU logs);
* `files/` holds `dictionary.sqlite` (99 MB total), `profileInstalled`, and a live
  `user.db` + `user.db-journal` — the offline dictionary is installed and the app is writing
  favourites/history locally;
* a phone-to-PC request reached FastAPI through the USB mapping
  (`GET /api/v1/health 200` logged from `127.0.0.1`), so login and AI calls will work on the
  device without hosting anything;
* `FLAG_SECURE` is active: `adb exec-out screencap` returns a black frame, which is exactly
  the behaviour the hardening commit was for (screenshots and the recents thumbnail are
  blocked by design, so visual checks need the phone's own screen).

Not exercised on the phone yet: signup/login (the account screen is a Phase 4 placeholder),
AI fallback (needs provider keys), and anything about a restart surviving the in-memory
token — that is the `flutter_secure_storage` item in Phase 4.
