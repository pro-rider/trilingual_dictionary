# CONTRIBUTING.md — Developer Guide

Two codebases in one product:

```
Dictionery\
├─ trilingual_dictionary\   Flutter app (git repo, branch main, remote pro-rider/trilingual_dictionary)
└─ backend\                 FastAPI service (currently NOT a git repo)
```

---

## 1. Prerequisites

| Tool | Version used | Notes |
|---|---|---|
| Flutter | stable (Dart SDK `^3.12.2` per `pubspec.yaml`) | `C:\flutter\bin\flutter.bat` on this machine |
| Git | any recent | `C:\Program Files\Git\cmd\git.exe` |
| Python | **3.11+** (`requires-python = ">=3.11"`) | backend venv |
| PostgreSQL / Docker | optional | only for favorites & feedback, or `scripts/seed_database.py` |

**`git` must be on `PATH` before running Flutter.** Flutter shells out to git and
fails with `Unable to find git in your PATH`. Prefix every PowerShell session:

```powershell
$env:Path = "C:\Windows\System32;C:\Windows;C:\Program Files\Git\cmd;C:\flutter\bin;$env:Path"
flutter --version
```

---

## 2. First-time setup

```powershell
cd C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary
flutter pub get

cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env      # then edit; never commit .env
```

`.env` minimum for a working offline backend:

```
AI_ENABLED=false
DATASET_PATH=data/seed/en_zh_ne.json
DATASET_VERSION=1
```

For AI features set `AI_ENABLED=true` and provide one key
(`GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY`) — or the legacy
`AI_API_KEY` + `AI_MODEL`, which Groq falls back to.

---

## 3. Running

```powershell
# backend (must be started from the backend\ directory: DATASET_PATH is relative)
cd C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
# → http://127.0.0.1:8000/docs
# → http://127.0.0.1:8000/api/v1/health

# app
cd C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary
flutter run                                            # desktop target, 127.0.0.1:8000
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000   # Android emulator
```

Sanity checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
(Invoke-RestMethod http://127.0.0.1:8000/api/v1/providers) | ConvertTo-Json -Depth 6
```

Build caveats: `INTERNET` is in the main manifest, so both debug and release can
reach the network. Cleartext `http://` is enabled **only in the debug manifest**,
so a release build needs an HTTPS `API_BASE_URL`. iOS exempts `localhost` only.
`flutter build apk --debug` is verified to produce a working APK (2026‑11‑07).

Windows desktop builds need two machine-level prerequisites that are easy to trip over:

1. **`nuget.exe` on `PATH`** — `flutter_tts` fetches its Windows speech dependency
   through NuGet; without it CMake fails with `nuget.exe not found`. On this machine
   it lives at `%LOCALAPPDATA%\Programs\nuget\nuget.exe`.
2. **Plugin links** — Flutter registers Windows plugins by creating symlinks under
   `windows\flutter\ephemeral\.plugin_symlinks`. Symbolic-link creation is blocked on
   this machine (`mklink /D` returns "The parameter is incorrect"), so that folder
   holds directory **junctions** instead: `mklink /J <link> <pub-cache package path>`,
   one per entry under `plugins.windows` in `.flutter-plugins-dependencies`. If a build
   fails with `PathNotFoundException: Cannot create link … errno = 2`, recreate the
   missing junction instead of deleting the folder.

---

## 4. Checks before every commit

```powershell
cd C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary
flutter analyze          # must be: No issues found!
flutter test             # must pass
dart format --output=none --set-exit-if-changed lib test

cd backend
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m scripts.validate_dataset   # after any dataset edit
```

There is **no CI**. These commands are the gate; a PR that does not show their
output is not reviewable.

---

## 5. Repository layout

```
trilingual_dictionary/
├─ lib/
│  ├─ main.dart, app/{app,router}.dart, app/theme/
│  ├─ core/        constants, normalizer, api_config, supabase_config, errors/
│  ├─ data/        api_client, dictionary_repository, providers, auth_provider, models/
│  └─ features/    home, search, result, analyze, detail, history, favorites, auth, settings, onboarding, splash
├─ assets/data/en_zh_ne.json        (copy #1)
├─ test/widget_test.dart
├─ android/ ios/ windows/ linux/ macos/ web/
├─ pubspec.yaml
└─ (docs) AGENTS, ARCHITECTURE, ENV-CONTRACTS, API-CONTRACTS, MODEL-CONTRACTS,
         DATA-GOVERNANCE, IMPACT-MAP, CHANGE-SCOPE, TESTING, PERFORMANCE-BUDGET,
         SECURITY, CONTRIBUTING

backend/
├─ app/
│  ├─ main.py
│  ├─ api/{router.py, deps.py, v1/*.py}
│  ├─ core/{config, security, exceptions}.py
│  ├─ schemas/search.py
│  ├─ services/{dataset, search, sentence_generator, quality, fallback_templates}.py
│  ├─ text_analysis/{segmenter, analyzer, phrases, schemas}.py
│  ├─ ai/{base, providers, failover, provider}.py
│  ├─ models/{word, cloud}.py, db/{base, session}.py
├─ data/seed/en_zh_ne.json          (copy #2, identical)
├─ scripts/{seed_database, validate_dataset}.py
├─ tests/                           35 tests
├─ alembic/, alembic.ini, docker-compose.yml, requirements.txt, .env.example
```

---

## 6. Git workflow

1. Branch from `main`: `git switch -c feature/<short-name>` or `fix/<short-name>`.
2. One logical change per branch; keep the diff small (`CHANGE-SCOPE.md` §7).
3. If git identity is not configured on the machine, set it locally (do not rely
   on a global identity):
   ```powershell
   git config user.name  "pro-rider"
   git config user.email "pro-rider@users.noreply.github.com"
   ```
4. Commit message: `area: imperative summary`
   - `text_analysis: real Chinese segmentation`
   - `app: fix favorites navigation`
   - `docs: add API contracts`
   - `data: add 5 water-related entries (v2)`
5. Push to a branch, open a PR describing: problem, approach, verification
   (command output), contract/docs impact, screenshots for UI changes.
6. Squash-merge by default; never force-push a shared branch.

**Backend is not under version control right now.** Do not `git init` it, move it
into the app repo, or add it to `.gitignore` without explicit approval — the
layout decision is open.

---

## 7. Dart / Flutter conventions

- `flutter_lints` (see `analysis_options.yaml`); prefer `const`, `final`, named
  parameters, and exhaustive `switch` on enums.
- File names `snake_case.dart`, classes `UpperCamelCase`, providers
  `xxxProvider`, notifiers `XxxNotifier`.
- One screen per file; private widgets start with `_`.
- Imports: `dart:` → `package:` → relative, blank line between groups.
- No `print`; no hardcoded colors outside `constants.dart`/theme; no magic
  spacing duplicated across screens (reuse the existing 12/16/24 rhythm).
- Navigation via `context.go/push` only (go_router). `Navigator.pushNamed` is a
  bug in this codebase.
- Every `family` key needs `==`/`hashCode`.
- Strings that users read in English today; there is no localization framework
  (`intl` is a dependency but no `.arb` files exist). Adding i18n is an
  architectural change — propose it first.

### Python conventions

- Python 3.11+, type hints, `from __future__ import annotations` where present.
- Pydantic v2 models at the boundary; domain logic in `services/` or
  `text_analysis/`; routers thin.
- AI access only through `app/ai/provider.py`.
- No new hard dependency without approval; `jieba` must stay optional with the
  greedy fallback intact.
- Format with a consistent style already in the repo (4 spaces, double quotes,
  blank line between top-level defs); keep line length ≈ 79–88.

---

## 8. Adding things

### A dictionary entry (see `DATA-GOVERNANCE.md` §7)

1. Edit `backend/data/seed/en_zh_ne.json`; keep the sense schema.
2. `python -m scripts.validate_dataset` → must print OK.
3. Copy the file to `assets/data/en_zh_ne.json`.
4. Bump `dataset_version` in JSON + `config.py` + `AppConstants`.
5. Compare hashes; run both suites; search the new word in app and API.

### A screen

1. `lib/features/<name>/<name>_screen.dart` — `Scaffold`, uses `LanguageColors`,
   no data fetching inline.
2. Provider in the same folder if it needs data; register in `data/providers.dart`
   only if shared.
3. Route in `lib/app/router.dart` + a way to reach it (do not orphan screens).
4. `flutter analyze`, manual walk including back navigation, 1.4× text scale.

### A backend endpoint

1. Schema in `app/schemas/search.py`, router module in `app/api/v1/`, register in
   `app/api/router.py`.
2. Service function with the logic; no DB/HTTP in the router body.
3. Test in `tests/test_*.py` asserting domain facts.
4. Update `API-CONTRACTS.md` (path, fields, errors) and the app's `ApiClient` only
   if the app consumes it.

### A provider (LLM)

1. Subclass `LLMProvider` (`app/ai/base.py`): `name`, `api_key`, `model`,
   `timeout`, `enabled`, `complete(system_prompt)`.
2. Register in `app/ai/providers.py` and add config fields + `.env.example`.
3. Add a `FakeProvider`-style test for its failure modes; update
   `MODEL-CONTRACTS.md`.

---

## 9. Review expectations

A reviewer checks, in this order:

1. Does it solve the stated problem without touching unrelated code?
2. `ARCHITECTURE.md` and `CHANGE-SCOPE.md` respected (layers, provider types,
   router, no new deps)?
3. Contract impact: wire format, env var, dataset, prompt — is the matching doc
   updated?
4. Tests: do they fail without the fix? Are they deterministic and offline?
5. Security: any secret, log of user text, cleartext, or permission change?
6. Performance: any new per-frame work, per-request file read, or extra network
   call?
7. Docs/commit message quality.

Reviewers may reject for scope, not only for correctness. Re-submit a smaller
change instead of arguing.

---

## 10. Reporting a problem

- Bug: file, line, exact input, expected vs actual, and whether it reproduces
  offline (`AGENTS.md` §9 lists known defects — don't report those as new).
- Security: follow `SECURITY.md` §11 (private report first).
- Data error: sense id + the wrong field + a source, so it can be reviewed rather
  than patched blindly.
