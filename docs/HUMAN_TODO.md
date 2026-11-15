# Human TODO — what only a person can do

Ordered by what unblocks the most. Every number is a row count read from the
database or a file in `review/`; every estimate says how it was derived.

## 1. Native Nepali review — the largest and most blocking item

| what | rows | file(s) | estimate |
|---|---|---|---|
| launch-set Nepali glosses (Tier 1+2) | 2,858 | `review/nepali-launch-part-01..06.xlsx` | ~95 h at 30 rows/h |
| remaining machine glosses outside the launch set | 387 | same topic, later batches | ~13 h |

- Who: a native Nepali speaker. A fluent second-language speaker is not enough
  for judging register and naturalness, which is what "reviewed" claims.
- How: read each row, fill `decision` (`approve` / `edit` + `edited_text` /
  `delete`). Blank means unreviewed and is never treated as approval.
- Apply with `python tools/import_review.py --file review/nepali-launch-part-01.xlsx --dry-run`
  first, then without `--dry-run`. `approve` sets `ne_status = 'reviewed'`.
- Practical advice: do one 500-row file end to end first and check the import
  report before committing to the rest.

## 2. Chinese high-frequency definitions

| what | rows | file(s) | estimate |
|---|---|---|---|
| Tier 1+2 entries whose Wiktionary gloss was routed to review | 5,140 | `review/chinese-highfreq-part-01..11.xlsx` | ~85 h at 60 rows/h |

- Who: a Chinese reader (native or near-native) who can spot a classical sense
  where a modern one is meant.
- Why it was not automated: for words like 的 the Wiktionary gloss is
  "白色；箭靶中心". Importing that would be worse than an empty field.

## 3. New words (1,348)

| what | rows | file(s) | estimate |
|---|---|---|---|
| 320 already human-written — confirm or reject | 320 | `review/new-words-part-01.xlsx` | ~10 h |
| 737 AI-filled — review English + Nepali | 737 | parts 1–2 | ~30 h |
| 291 still empty — need translation input | 291 | part 3 | ~8 h, after the provider decision in item 4 |

This topic also sets policy: a word not in CC-CEDICT is a judgement call ("is this
standard Mandarin?"). Decide once, at the top of the file, and apply consistently.

## 4. Choose and pay for an AI provider

- Status: **no working provider**. Groq is region-blocked (403/1010), Gemini
  times out, OpenRouter's free allowance is exhausted (402).
- Needed from you: vendor choice + API key put into environment variables
  (`PAID_PROVIDER_NAME`, `PAID_PROVIDER_URL`, `PAID_PROVIDER_KEY`,
  `PAID_PROVIDER_MODEL`, then `AI_ALLOW_PAID=true`). Never commit the key.
- Verify after wiring: `python backend/tools/provider_health.py` must print
  `working` for that provider before the generator is re-run.
- Unblocks: the 291 pending new words, and example-sentence generation.

## 5. Legal review of the drafts

- `CREDITS.md`, `PRIVACY_POLICY.md`, `docs/PLAY_DATA_SAFETY.md`,
  `docs/IMAGE_AUDIT.md` — all marked DRAFT.
- Fill `[CONTACT_EMAIL]`, `[APP_NAME]`, `[COMPANY_LEGAL_NAME]`.
- Confirm CC BY-SA 4.0 obligations for a commercial store listing, and whether a
  `LICENSE-DATA` file must be shipped next to the app licence.
- Answer the three **DECISION NEEDED** items in `docs/PLAY_DATA_SAFETY.md`:
  cloud sync of favourites, device/IP counting claim, crash reporting.

## 6. Real-device test list (not run — no device was available here)

| # | scenario | pass criterion |
|---|---|---|
| 1 | low-end phone (2 GB RAM), first launch | progress screen appears, unpack completes, search works; no OOM |
| 2 | device with < 120 MB free before first launch | clear "needs ~100 MB" message, retry button works, **no partial file left** |
| 3 | kill the app mid-unpack, relaunch | recovers (stale `.part` discarded), second attempt succeeds |
| 4 | upgrade from the previous build | favourites, history and AI results intact; dictionary content is the new one |
| 5 | airplane mode | search, entry view, images (if cached) work; AI actions show the honest "not found yet" |
| 6 | rotate + background/foreground on an entry screen | no crash, state kept |
| 7 | traditional-character input on a device without a Chinese IME | simplified result returned |

## 7. Store listing and submission

1. Fill the Data Safety form from `docs/PLAY_DATA_SAFETY.md`.
2. Attach the privacy policy URL once published.
3. Screenshots from the real-device run above (item 6), not from a simulator.
4. Release notes must state that machine translations are labelled as such.
5. Rollout: internal → closed → production, one build at a time; the asset
   unpack path is the highest-risk change in this release.

## Commands to run first

```powershell
# from the repo root
backend\.venv\Scripts\python.exe backend\tools\check.py        # full pipeline
backend\.venv\Scripts\python.exe backend\tools\check.py --fast # backend only
backend\.venv\Scripts\python.exe backend\tools\metrics.py       # current numbers
backend\.venv\Scripts\python.exe backend\tools\backup_db.py     # backup + checksum
```

`make` targets exist for the same four commands if `make` is installed.

---

## 8. Auth system (branch `auth-system`) — human-only steps

Phase 1 is four **unapplied** migration files under `supabase/migrations/`,
described in `docs/AUTH-SCHEMA.md`. Nothing below can be done by an agent:
each step needs an account, a DNS record or a legal judgement.

| # | Step | Blocks | Notes |
|---|---|---|---|
| 1 | Create the Supabase project and record the project ref | Phase 1 apply, Phase 2 | Free tier covers launch volumes |
| 2 | Decide the JWT signing mode: keep the legacy **HS256** secret, or move to asymmetric keys | Phase 2 | `backend/app/core/security.py` assumes HS256 today; with asymmetric keys the backend must verify against the project's JWKS instead |
| 3 | Apply the four migrations (`supabase db push`, or paste each file in the SQL editor **in filename order**) | Phase 2 | — |
| 4 | Enable `pg_cron` (Database → Extensions) before step 3 | retention | Without it the migrations still succeed with a notice; the three purge functions then need a FastAPI scheduler |
| 5 | Add custom SMTP (Resend / Brevo / SendGrid) under Authentication → Emails; set code expiry to 10 minutes | Phase 4 | One template for signup **and** reset — the wording must not reveal whether an address exists |
| 6 | Publish SPF, DKIM and DMARC for the sending subdomain | launch | Without them codes land in spam and signup looks broken |
| 7 | Put the **service-role** key and the JWT secret in the FastAPI host's environment (`backend/.env` locally) only | Phase 2 | Never in `lib/`, never in git — `docs/SECURITY.md` states this |
| 8 | Register the mobile deep-link scheme in Supabase (Authentication → URL configuration) | Phase 4 | No web origin is needed while web is deferred (A20) |
| 9 | Deferred: choose the web login host (Next.js on Vercel vs the Flutter web build) | later | Superseded by A20 — mobile only for now. The Flutter web target still does not boot today (`dart:io`, `path_provider`, `sqflite`) |
| 10 | Legal review of the privacy-policy wording for `security_events` (salted IP hashes, 30-day retention) | launch | The promise must match migration 3 exactly |
| 11 | Penetration test before public launch | launch | Required by the brief |
| 12 | Publish the **static account-deletion page** and enter its URL in Play Console → Data deletion | launch | Per A21: the page describes the in-app path (`DELETE /auth/account`) and the email fallback; it does not delete anything itself |
| 13 | Give the staging project URL, anon key, service-role key and signing mode to run `supabase/tests/run_migration_checks.py` against real Supabase | Phase 2 | Without these the staging run stays NOT VERIFIED (A23) |
| 14 | **Disable public sign-up in Supabase** (Authentication → Providers → Email → "Allow new users to sign up" OFF) | launch | With no anon key in the app (A24) nothing can reach `/auth/v1/signup` anyway, but the switch removes the path entirely if a key ever leaks |
| 15 | If any APK, internal test build or Play upload ever contained a Supabase URL + anon key, **treat that key as public**: rotate it, then confirm sign-up is off | launch | Removing the code later does not un-ship it. `lib/core/supabase_config.dart` never held a real value and is now deleted; only you know whether an earlier build shipped |
| 16 | Set `AUTH_CODE_PEPPER` (≥ 16 random chars) in the FastAPI environment | Phase 2 | The flow returns 503 "Auth not configured" without it, rather than hashing a 6-digit code with an empty key |
| 17 | Set `TRUSTED_PROXIES` to your proxy CIDRs (or leave empty when FastAPI is the only hop) | Phase 3 | Until this matches the real edge, per-IP limits count either the proxy or a spoofable header (`backend/tests/test_net.py` proves the ignore-path) |
| 18 | Phase 4: store the refresh token in `flutter_secure_storage` | Phase 4 | The token is memory-only today, so the 30-day server session is unusable after an app restart (A30) |
| 19 | Run `backend\tools\update_disposable_domains.py` on the server, then restart | launch | The generated 10k-domain list is git-ignored because upstream reports licence `NOASSERTION`; the repo ships a 340-domain floor (A31) |
| 20 | Add `AUTH_DISPOSABLE_ALLOW_DOMAINS` when a real user is wrongly blocked | launch | Domain-level override, no redeploy of the list needed |
| 21 | Keep PR #2 targeting `auth-system`; do not merge to `main`, do not release from this branch | now | The account screen is still a placeholder until Phase 4; the app has no working login UI |
| 22 | Replace the whole-window `FLAG_SECURE` with a per-screen toggle (method channel) covering only auth, code, password and session screens | auth hardening | Today `MainActivity.kt` applies the flag to every window in **release** builds only (`ApplicationInfo.FLAG_DEBUGGABLE` guards debug). Consequence: in release a user cannot screenshot an ordinary entry page either. Needs a channel call the auth routes raise and the rest lower |
