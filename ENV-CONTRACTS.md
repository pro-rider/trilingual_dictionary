# ENV-CONTRACTS.md — Environment & Configuration

Rules: **no secret in git**, **no environment-specific URL hardcoded in Dart logic**,
**one owner per variable**. If you add a variable, add a row here in the same change.

Two separate config systems:

| Part | Mechanism | File |
|---|---|---|
| Flutter app | compile-time `--dart-define` + constants in source | `lib/core/api_config.dart`, `lib/core/supabase_config.dart` |
| Backend | `.env` via pydantic-settings | `backend/app/core/config.py`, `backend/.env` |

---

## 1. Flutter — compile-time configuration

### 1.1 `API_BASE_URL`

| | |
|---|---|
| Definition | `lib/core/api_config.dart` — `const String.fromEnvironment('API_BASE_URL', defaultValue: 'http://127.0.0.1:8000')` |
| Type | String URL, no trailing slash |
| Default | `http://127.0.0.1:8000` |
| Override | `flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000` |
| Used by | `apiClientProvider` → `Dio(BaseOptions(baseUrl: …))` |
| Sensitivity | none (public endpoint) |
| Validation | none at runtime; an invalid URL simply fails every call and the app silently falls back to offline |

**Platform matrix**

| Target | Correct value | Why |
|---|---|---|
| Windows / macOS / Linux desktop | `http://127.0.0.1:8000` | backend on the same machine |
| Android emulator | `http://10.0.2.2:8000` | `127.0.0.1` inside the emulator is the emulator itself |
| iOS simulator | `http://127.0.0.1:8000` | shares the host loopback |
| Physical phone | `http://<host-LAN-IP>:8000` | same Wi‑Fi; backend must bind `0.0.0.0` |
| Web (`flutter run -d chrome`) | LAN IP, not `127.0.0.1` | browser origin restrictions; Supabase is disabled on web |

Networking constraints for non-desktop targets (see `SECURITY.md` §3):

- `INTERNET` is declared in the **main** manifest, so debug and release builds can
  both reach the network.
- Cleartext `http://` is allowed **only in debug** (`android/app/src/debug/AndroidManifest.xml`);
  release builds require HTTPS. On iOS, `Info.plist` exempts `localhost` /
  local networking only — a physical iPhone on a LAN IP needs its own exception.
- So: `http://` + `127.0.0.1` works on desktop, Android emulator and iOS
  simulator in debug; a release build needs an HTTPS backend.

### 1.2 `ApiConfig.timeout`

`Duration(seconds: 25)` applied to both `connectTimeout` and `receiveTimeout`.
The batched analysis call can take ~4 s with a warm LLM, so 25 s is the contract;
do not lower it below 15 s.

### 1.3 Supabase (app side)

| | |
|---|---|
| Definition | `lib/core/supabase_config.dart` — `static const String url = ''`, `anonKey = ''` |
| Type | String |
| Default | empty ⇒ cloud features disabled |
| Configured when | both non-empty **and** `!kIsWeb` |
| Used by | `main.dart` (init), `auth_provider.dart`, `favorites_repository.dart`, `settings_screen.dart` |
| Sensitivity | anon key is public-by-design; **never** put a service-role key here |

These are compile-time constants in a **tracked source file**, which is a known
weak point: a filled-in key would be committed. Preferred direction (not yet
implemented) is `--dart-define=SUPABASE_URL=… --dart-define=SUPABASE_ANON_KEY=…`
read via `String.fromEnvironment`. Do not change this silently — it alters how the
app is built.

Table name: `SupabaseConfig.favoritesTable = 'favorites'` (must match the SQL in
that file's comment and with `backend/app/models/cloud.py`).

### 1.4 Flutter build modes

| Mode | Command | Backend expected |
|---|---|---|
| debug | `flutter run` | local, cleartext allowed |
| profile | `flutter run --profile` | same |
| release | `flutter build apk --release` | works, but **cleartext HTTP is blocked** — needs an HTTPS `API_BASE_URL` |

There are no product flavors (`dev`/`staging`/`prod`); the only switch is
`API_BASE_URL` via `--dart-define`.

---

## 2. Backend — `.env` variables

Loaded by `app/core/config.py` (`Settings(BaseSettings)`, `env_file=".env"`,
`extra="ignore"`). Unknown keys are ignored silently — typos therefore fail
silently too.

### 2.1 Core

| Variable | Type | Default | Validation | Secret | Used in |
|---|---|---|---|---|---|
| `APP_NAME` | str | `Trilingual Dictionary API` | — | no | `main.py` title, `/` |
| `VERSION` | str | `0.1.0` | — | no | `/`, `/health` |
| `CORS_ORIGINS` | `list[str]` (JSON array) | `["*"]` | must be valid JSON when set | no | `CORSMiddleware` |
| `DATASET_PATH` | str path | `data/seed/en_zh_ne.json` | file must exist or every lookup raises `FileNotFoundError` | no | `services/dataset.py` |
| `DATASET_VERSION` | int | `1` | — | no | `/health` echo |
| `DATABASE_URL` | str DSN | `postgresql+psycopg://postgres:postgres@localhost:5432/trilingual_dictionary` | reachable only for favorites/feedback | **yes** (has password) | `db/session.py` |

### 2.2 AI — master switch and failover

| Variable | Type | Default | Validation / effect | Secret | Used in |
|---|---|---|---|---|---|
| `AI_ENABLED` | bool | `false` | `false` ⇒ no AI anywhere, even with keys | no | `ai.provider.ai_enabled()` |
| `AI_PROVIDERS_ORDER` | csv str | `groq,gemini,openrouter` | names not matching a built provider are dropped | no | `_build_service()` |
| `AI_MAX_RETRIES` | int | `1` | attempts = retries + 1 per provider | no | failover |
| `AI_RETRY_BACKOFF_SECONDS` | float | `0.5` | sleeps between retries | no | failover |
| `CIRCUIT_FAIL_THRESHOLD` | int | `3` | consecutive failures before the circuit opens | no | failover |
| `CIRCUIT_COOLDOWN_SECONDS` | int | `30` | how long an open circuit is skipped | no | failover |

A provider is **active** only when `ENABLED=true` **and** it has a key.
`ai_enabled()` additionally requires `AI_ENABLED=true` and at least one active
provider.

### 2.3 Providers

| Variable | Type | Default | Notes | Secret |
|---|---|---|---|---|
| `GROQ_API_KEY` | str | `''` | empty ⇒ falls back to legacy `AI_API_KEY` | **yes** |
| `GROQ_MODEL` | str | `''` (falls back to `AI_MODEL`, then `openai/gpt-oss-120b`) | — | no |
| `GROQ_TIMEOUT` | float | `40` | seconds, per HTTP call | no |
| `GROQ_ENABLED` | bool | `true` | — | no |
| `GROQ_BASE_URL` | str | `https://api.groq.com/openai/v1` | OpenAI-compatible | no |
| `GEMINI_API_KEY` | str | `''` | sent in the URL query (`?key=`), not a header | **yes** |
| `GEMINI_MODEL` | str | `gemini-2.0-flash` | `.env.example` currently shows `gemini-3.8-flash` — **the two disagree; treat `config.py` as authoritative** | no |
| `GEMINI_TIMEOUT` | float | `40` | — | no |
| `GEMINI_ENABLED` | bool | `true` | — | no |
| `GEMINI_BASE_URL` | str | `https://generativelanguage.googleapis.com/v1beta` | — | no |
| `OPENROUTER_API_KEY` | str | `''` | — | **yes** |
| `OPENROUTER_MODEL` | str | `meta-llama/llama-3.1-70b-instruct` | must be a model the OpenRouter account can use | no |
| `OPENROUTER_TIMEOUT` | float | `40` | — | no |
| `OPENROUTER_ENABLED` | bool | `true` | — | no |
| `OPENROUTER_BASE_URL` | str | `https://openrouter.ai/api/v1` | — | no |

### 2.4 Legacy single-provider fields

Kept for backward compatibility; **Groq prefers its own fields**:

| Variable | Type | Default | Behaviour |
|---|---|---|---|
| `AI_API_KEY` | str | `''` | used as the Groq key when `GROQ_API_KEY` is empty |
| `AI_MODEL` | str | `''` | used as the Groq model when `GROQ_MODEL` is empty |
| `AI_BASE_URL` | str | `https://api.groq.com/openai/v1` | used as Groq base URL |

On the current dev machine `AI_ENABLED=true`, `GROQ_API_KEY` is **empty**, and
`AI_API_KEY` holds a working Groq key — so Groq runs off the legacy field. Passing
`/api/v1/providers` shows the truth (`active`, `last_error`, latency).

### 2.5 Auth

| Variable | Type | Default | Validation | Secret | Used in |
|---|---|---|---|---|---|
| `SUPABASE_URL` | str | `''` | informational; app has its own copy | no | placeholder |
| `SUPABASE_JWT_SECRET` | str | `''` | empty ⇒ `/me`, `/favorites`, `/feedback` return **503**; HS256 only; use the full ≥32-byte secret (tests use an 11-byte string and PyJWT warns "InsecureKeyLength") | **yes** | `core/security.py` |

---

## 3. Runtime modes

| Mode | How | AI | DB | Notes |
|---|---|---|---|---|
| **dev (offline)** | `uvicorn app.main:app --reload --port 8000` with `AI_ENABLED=false` | off | not needed | 6 dataset words only; the honest baseline |
| **dev (AI)** | same, `AI_ENABLED=true` + at least one key | on | not needed | current local `.env` |
| **test** | `pytest` | forced off by `tests/conftest.py` (autouse fixture flips `settings.ai_enabled`) | not needed (no DB tests) | hermetic, no network |
| **staging** | *not defined* | — | — | no Dockerfile, no compose for the API |
| **production** | *not defined* | — | — | no Dockerfile, CI, or migration step |

`docker-compose.yml` only starts **Postgres 16** (`postgres/postgres`, port 5432,
volume `pgdata`). The API itself is run from the venv.

---

## 4. Where config is consumed (change map)

| Setting | Consumed by | Breakage if wrong |
|---|---|---|
| `API_BASE_URL` | all `ApiClient` calls | silent offline mode (no error shown to users) |
| `ApiConfig.timeout` | Dio | long analysis requests abort at 25 s |
| Supabase url/anonKey | `main.dart`, auth, favorites | cloud features hidden; no crash |
| `DATASET_PATH` | every lookup, analysis, sentence | 500 `FileNotFoundError` |
| `CORS_ORIGINS` | browser clients | web build cannot call the API |
| `AI_ENABLED` | search fallback + analysis | unknown words → `null` / `degraded` |
| `AI_PROVIDERS_ORDER` | failover chain | only listed, known names are used |
| timeouts | httpx per provider | provider treated as failed → next in chain |
| `SUPABASE_JWT_SECRET` | protected endpoints | 503 for all authenticated calls |

---

## 5. Adding a variable — checklist

1. Add the field to `Settings` in `backend/app/core/config.py` with a safe default.
2. Add it to `backend/.env.example` **with a comment**; never add a real value.
3. Add a row to the table above (type, default, validation, secret?, consumer).
4. If the app needs it, use `--dart-define` — do not hardcode, do not commit.
5. Verify: restart the API, hit `/api/v1/health` and the affected endpoint.
6. If it is sensitive, confirm no log line prints it and `.env` is git-ignored
   (it is — `backend/.gitignore` has `.env`, `*.env`, `!.env.example`).
