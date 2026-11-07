# SECURITY.md — Security & Privacy

Scope: Flutter client, FastAPI backend, dictionary data, and the third-party
services they talk to (Supabase, Groq, Google Gemini, OpenRouter).

Current posture summary (v0.1.0): **local-development grade**. No TLS in the
default configuration, no CI secret scanning, release signing uses debug keys,
and no published build exists. Treat everything below as requirements before any
public release — the gaps are listed explicitly rather than implied.

---

## 1. Assets and sensitivity

| Asset | Where it lives | Sensitivity | Notes |
|---|---|---|---|
| LLM provider keys (Groq / Gemini / OpenRouter) | `backend/.env` only | **critical** | server-side; never in the app |
| `SUPABASE_JWT_SECRET` | `backend/.env` | **critical** | HS256 signing secret; rotate if exposed |
| `DATABASE_URL` (contains DB password) | `backend/.env` | **high** | default dev DSN is `postgres:postgres` |
| Supabase project URL + anon key | `lib/core/supabase_config.dart` | medium (public by design) | anon key is safe to ship; **service-role key is not** |
| User email / uid | Supabase, `/me` responses | **personal data** |
| Saved favorites | device `shared_preferences` + optional Supabase table | personal preference |
| Search history | memory only (lost on exit) | personal data, low durability |
| Settings | memory only | none |
| Feedback comments | Postgres `feedback` table | user-generated content, may contain personal data |
| Dictionary dataset | `assets/data/…` + `backend/data/seed/…` | public content | licence/attribution in `DATA-GOVERNANCE.md` |

Rule of thumb: **anything the backend can bill, prove identity with, or reveal
about a person is server-side and encrypted at rest in production.**

---

## 2. Credentials

- Secrets live only in `backend/.env`; `.gitignore` ignores `.env`, `*.env` and
  keeps `.env.example`. `.env.example` must contain placeholders only.
- The Flutter app must **never** hold an LLM key. All AI traffic goes through the
  backend; if a key ever appears in `lib/`, treat it as leaked.
- `lib/core/supabase_config.dart` currently holds `url`/`anonKey` as compile-time
  constants. They are empty today. A filled-in **anon** key is acceptable; a
  service-role key would be a critical leak. Preferred hardening: move both to
  `--dart-define` so a build cannot commit them.
- Keys must be rotated when: a machine is shared/returned, a repository becomes
  public, a `.env` is pasted into a chat/issue/log, or a build artefact is
  distributed with a baked-in key.
- `.env` values are never printed in docs, tickets, screenshots, or agent output.
  Refer to them as `${GROQ_API_KEY}` etc.

---

## 3. Transport

| Environment | Current | Required |
|---|---|---|
| Dev (desktop) | plain `http://127.0.0.1:8000` | acceptable (loopback only) |
| Dev (phone on LAN) | plain `http://<lan-ip>:8000` | acceptable on a trusted network **only**; do not use on public Wi‑Fi |
| Staging / production | **does not exist** | HTTPS with a valid certificate; backend behind a reverse proxy |

Consequences already in the codebase:

- **Android release** manifest lacks `INTERNET`; cleartext HTTP is blocked by
  default on Android 9+. If you add them, add them **per build type**: allow
  cleartext in the debug manifest only (`android:usesCleartextTraffic="true"` or
  a `network_security_config.xml` limited to the dev host). Never enable global
  cleartext in the release manifest.
- **iOS** `Info.plist` has no `NSAppTransportSecurity`; `http://` is blocked by
  ATS. Use an `NSExceptionDomains` entry for `localhost` in a **debug** plist, or
  run an HTTPS backend. Do not set `NSAllowsArbitraryLoads`.
- There is no certificate pinning; acceptable while TLS validation is on.
- CORS default is `["*"]`. Acceptable for local tools with no cookies/credentials;
  before any deployment set an explicit origin list and never combine `*` with
  credentialed requests.

---

## 4. Authentication & authorisation

- The app authenticates against **Supabase Auth**; the backend verifies the
  resulting JWT (HS256) with `SUPABASE_JWT_SECRET`.
- If the secret is empty, protected endpoints return **503 "Auth not configured"**
  — fail closed, which is correct. Do not make them "open when unconfigured".
- `sub` is the user id. Every favorites/feedback write is scoped by `user_id` taken
  from the token, never from the request body. There is no admin role and no
  cross-user read endpoint.
- Token lifetime/refresh is Supabase's responsibility; the app persists the
  session via the SDK. Do not log the session object.
- Known weakness: the app writes favorites **directly** to the Supabase table
  using the anon key, so row-level security in Supabase is the only guard. Any
  deployment of this feature **must** enable RLS with `user_id = auth.uid()`
  policies; otherwise one user could read another's favorites.
- Short test secrets (e.g. `"test-secret"`) produce PyJWT `InsecureKeyLength`
  warnings. That is expected in tests and forbidden in real deployments (use the
  full secret Supabase issues).

---

## 5. Local storage

| Data | Store | Protection today | Recommendation |
|---|---|---|---|
| Supabase session | SDK default (`shared_preferences`-backed) | none beyond OS sandbox | `flutter_secure_storage` if threat model includes rooted devices |
| Favorites | `shared_preferences` (plain) | none | acceptable (non-secret), document it |
| History | RAM | none | if persisted, keep it optional and clearable |
| Settings | RAM | n/a | — |
| Cached dictionary | app bundle | none (public data) | — |

Do not store tokens, emails, or feedback drafts in plain preferences. If you
persist history, add a "clear history" action in the same change.

---

## 6. Platform hardening gaps (must be fixed before publishing)

1. `android/app/src/main/AndroidManifest.xml` — no `INTERNET` permission; add it.
2. Release `signingConfig = signingConfigs.getByName("debug")` — **must** be
   replaced with a real keystore before any distribution; debug-signed releases
   are not publishable and are trivially re-signable.
3. `applicationId = com.example.trilingual_dictionary` — placeholder; change
   before store submission.
4. iOS ATS exception strategy (debug only) as described in §3.
5. No `flutter build` obfuscation (`--obfuscate --split-debug-info`) configured —
   optional, but recommended for release to slow reverse engineering of any
   embedded keys (there should be none).

---

## 7. Input validation & abuse resistance

Server-side (authoritative):

| Surface | Guard |
|---|---|
| `/search` | `q` 1–80 chars, enum `lang` |
| `/analyze/text` | `text` 1–4000 chars, ≤60 AI surfaces |
| `/suggest` | `q` 1–80 chars |
| `/feedback` | `field` ≤ 40, `comment` ≤ 2000 |
| JWT | signature + `sub` presence; `exp` validated by PyJWT |

Client-side limits are UX only; never rely on them.

- **SQL**: all DB access via SQLAlchemy ORM; no string-built SQL anywhere. Keep it
  that way.
- **Path handling**: `DATASET_PATH` comes from config, never from a request. No
  user input reaches the filesystem.
- **Prompt injection**: user text is embedded in the LLM prompt. Mitigations
  already in place — the system message is fixed, output must be JSON, results
  are matched back by surface, and AI output is marked non-authoritative. Residual
  risk: a malicious input could make the model emit wrong translations or prose;
  it cannot execute anything. Never treat model output as a command or a URL.
- **Cost abuse**: no rate limiting on AI endpoints. Before exposing the API
  publicly, add per-IP/per-user limits (the `_MAX_AI_SURFACES` cap bounds one call,
  not call volume).
- **DoS shapes**: 4000-char inputs × 60 surfaces × 40 s timeouts can exhaust a
  worker pool; add a request timeout at the proxy.

---

## 8. Logging & error hygiene

- Never log: API keys, Authorization headers, full `.env`, Supabase session
  objects, or full user text at INFO.
- Allowed: provider name, latency, retry count, circuit state, segment counts,
  error class names.
- `ApiError` messages are user-facing; do not put stack traces or DSNs in them.
- FastAPI's default 500 page is acceptable for now but must not echo exception
  text in production — add a handler that returns a generic message.
- The Flutter app must not display raw exception strings; `ApiClient` already
  collapses failures to `null`.

---

## 9. Dependency security

- App: caret ranges in `pubspec.yaml`, `pubspec.lock` committed (keep it
  committed for reproducible builds). Run `flutter pub outdated` periodically.
- Backend: `requirements.txt` uses lower bounds only (`>=`), so builds are not
  reproducible — pin exact versions (or add a lock) before deployment.
- Do not add a dependency that phones home with analytics; this app has no
  telemetry and should keep it that way.
- Review any package that requests network, contacts, storage, or location
  permissions on Android/iOS; the app currently needs only `INTERNET`.
- Audit commands: `flutter pub deps --style=compact`, `pip list --outdated`,
  `pip-audit` (if available).

---

## 10. Publishing on GitHub

1. `git status` must show no `.env`, no keystore, no `*.jks`, no service account
   JSON.
2. Search history, not just the tree: `git log -p --all | Select-String "API_KEY|SECRET|Bearer"` (or `gitleaks`). If a secret was ever committed, **rotate it** —
   rewriting history is not enough.
3. `backend/` is currently **not** a git repository. If it is added to this repo,
   add `.gitignore` first (it already excludes `.env`) and commit in a separate,
   reviewed change.
4. Publish a `LICENSE` and keep `README` honest about the 6-entry dataset.
5. Do not publish a build artefact signed with debug keys.
6. Keep `SECURITY.md` (this file) updated — a public repo with a security policy
   is treated more responsibly than one without.

---

## 11. Reporting a vulnerability

- Do not open a public issue for an exploitable finding. Report privately to the
  maintainer (repo owner `pro-rider`), with reproduction steps, affected
  component, and impact.
- Response targets: acknowledge within 72 h; critical fix within 7 days; rotate
  any exposed credential immediately, before the code fix.
- After a fix: add a regression test, note the issue in the release notes without
  revealing exploitation details, and credit the reporter if they want it.

---

## 12. Pre-release checklist

- [ ] No secret in `lib/`, `ios/`, `android/`, or git history
- [ ] `INTERNET` permission in the **release** manifest; cleartext allowed only in debug
- [ ] Release signing keystore configured; `applicationId` not `com.example.*`
- [ ] HTTPS endpoint; CORS restricted; no `*`
- [ ] Supabase RLS enabled on `favorites` (and any user table)
- [ ] `SUPABASE_JWT_SECRET` is the full-length secret; protected routes tested (503/401/200)
- [ ] AI endpoints rate-limited
- [ ] 500 responses do not leak internals
- [ ] Dependency versions pinned; `pubspec.lock` committed
- [ ] Privacy note published: user text is sent to third-party LLM providers
      (Groq / Google / OpenRouter) for translation; no analytics SDK present
