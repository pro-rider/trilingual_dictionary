# AGENTS.md — Instructions for AI Coding Assistants

Scope: this file governs any AI agent (or human acting through one) that edits the
Trilingual Dictionary codebase. Read it before touching code. It exists so the same
rules do not have to be re-explained in every prompt.

Companion documents — read the one that matches the task, not all of them:

| Task | Read |
|---|---|
| Any non-trivial task (migration, bulk write, a number used for a decision) | `PROTOCOL.md` |
| Understanding the system | `ARCHITECTURE.md` |
| Config / env vars | `ENV-CONTRACTS.md` |
| "What breaks if I change X?" | `IMPACT-MAP.md` |
| "How much am I allowed to change?" | `CHANGE-SCOPE.md` |
| API request/response shapes | `API-CONTRACTS.md` |
| AI / NLP behaviour | `MODEL-CONTRACTS.md` |
| Tests | `TESTING.md` |
| Secrets, privacy, GitHub | `SECURITY.md` |
| Dictionary data | `DATA-GOVERNANCE.md` |
| Latency / memory limits | `PERFORMANCE-BUDGET.md` |
| Dev workflow | `CONTRIBUTING.md` |

---

## 1. What this project is

A **Flutter** client (`trilingual_dictionary/`) + **FastAPI** backend (`../backend/`)
for a dictionary where you search in **English or Chinese** and get meanings plus
aligned example sentences in **English · 中文 · नेपाली**. Nepali is **output-only**.

Two codebases, one product. The app must always work with the backend **off**.

---

## 2. Before you change anything (mandatory sequence)

1. **Read the file you are about to change.** No edits from memory or from a
   filename guess.
2. **Grep for the symbol** across `lib/` and `backend/app/` before renaming or
   changing a signature (`rg "providerName|ClassName|/endpoint"`). A "local" change
   usually has 2–5 call sites.
3. **Check `IMPACT-MAP.md`** for the area — it lists the files that co-change.
4. **State the plan in one or two sentences** before writing code: what will change,
   what will deliberately not change.
5. **Reproduce first** for bug fixes (run the failing test, call the endpoint).
   Do not "fix" behaviour that already works.

If any step cannot be completed (file missing, test cannot run), stop and report
the blocker instead of guessing.

---

## 3. Hard rules

### Preserve

- **Existing functionality.** Every route in `lib/app/router.dart` must keep working;
  no screen may be removed or renamed without an explicit instruction.
- **Offline mode.** Any new feature must degrade to a sensible offline state. Never
  make the app unusable when `127.0.0.1:8000` is down.
- **The 3-language model.** English + Chinese input, Nepali output. Do not add a
  fourth language or make Nepali searchable without a written requirement.
- **Public API shapes.** Adding optional fields is allowed; renaming/removing fields
  in `backend/app/schemas/*` or `lib/data/models/*` is a breaking change.
- **The `null`-instead-of-throw contract** in `lib/data/api_client.dart`. Screens
  rely on it.

### Never

- Commit secrets. `.env`, API keys, JWT secrets, Supabase keys stay out of git
  (see `SECURITY.md`).
- Put an LLM/API key in the Flutter app. All AI calls go through the backend.
- Edit `build/`, `.dart_tool/`, `.gradle/`, `.venv/`, `pubspec.lock` by hand, or
  generated plugin registrants.
- Run `git push --force`, `git reset --hard`, or delete user data to "clean up".
- Refactor broadly (rename layers, introduce Clean Architecture, swap state
  management, replace `go_router`) as a side effect of a small task.
- Add a dependency without justification + approval (see §5).
- Invent metrics, model behaviour, or dataset contents. If something is not
  implemented, document that it is not implemented.

### Always

- Keep `flutter analyze` at **0 issues** and both test suites green.
- Keep the app's `assets/data/en_zh_ne.json` and the backend's
  `data/seed/en_zh_ne.json` **identical** (compare hashes) and bump the dataset
  version when either changes.
- Update the relevant document when you change a contract, an env var, or a rule
  (this repo treats docs as code).
- Report what you changed, what you verified, and what you did not verify.

---

## 4. Code conventions

### Dart / Flutter

- Dart 3, null-safety on, `flutter_lints` rules from `analysis_options.yaml`.
- `const` constructors wherever possible; `final` fields; no `var` for public
  member state.
- Widgets: one public widget per screen file; private helpers prefixed `_`.
- Named parameters with `required` for anything a caller could forget.
- Import order: `dart:` → `package:` → relative (`../../`).
- No `print()` in app code; use `debugPrint` only for transient diagnostics.
- Colors come from `LanguageColors` / `Color(0xFF…)` constants already in the file;
  do not introduce a new palette.
- Text must survive `textScale` 1.4 without overflow (test with the slider).
- Never call `Navigator.pushNamed` — this is a `MaterialApp.router` app; use
  `context.push()` / `context.go()` from `go_router`.

### Riverpod

- Keep the existing style: `Provider` for stateless singletons,
  `NotifierProvider` for mutable settings/history, `AsyncNotifierProvider` for
  persisted async state, `FutureProvider[.family]` for reads.
- **Any `family` argument class must implement `==` and `hashCode`** (see
  `SearchArgs`). Omitting this causes a permanent loading spinner.
- Use `ref.watch` in `build`, `ref.read` inside callbacks. Do not `watch` inside
  `initState`.
- Do not introduce `riverpod_generator` / codegen without approval.

### Python / FastAPI

- Python ≥ 3.11, type hints on public functions, `from __future__ import annotations`
  where the file already uses it.
- Pydantic v2 models for every request/response; no raw dicts leaving a router.
- Business logic in `app/services/` or `app/text_analysis/`; routers stay thin.
- AI calls only through `app/ai/provider.py` (which owns failover). Never call
  `httpx` to a model endpoint from a router or service.
- Raise `ApiError` for client-facing failures; let unexpected exceptions surface as
  500.
- Never log full prompts containing user text at INFO level; log counters and
  provider names instead.

---

## 5. Dependency policy

Adding a dependency requires (in the same change): what it does, why existing
code cannot do it, size/licence, and the fallback if it is unavailable.

- **Allowed without discussion:** Dart packages already in `pubspec.yaml`; Python
  stdlib; packages already in `requirements.txt`.
- **Requires approval:** any new Flutter plugin with native code; any Python
  package over ~10 MB; anything that phones home, collects analytics, or needs an
  account; anything GPL/AGPL-incompatible with the repo's current practice.
- **Specific case:** `jieba` is an approved backend dependency and **must stay
  optional** — `app/text_analysis/segmenter.py` falls back to greedy matching when
  the import fails. Never make jieba a hard import.

`shared_preferences`, `go_router`, `dio`, `flutter_riverpod`, `supabase_flutter`
are the app's current non-negotiable stack for this phase.

---

## 6. How to add things (patterns to copy)

| I need to… | Do this |
|---|---|
| Add a screen | new `lib/features/<name>/<name>_screen.dart` + route in `router.dart` + provider if it fetches |
| Add a backend endpoint | module in `backend/app/api/v1/`, register in `router.py`, schema in `app/schemas/search.py`, test in `tests/` |
| Add a dictionary word | edit **both** JSON copies, keep the `Sense` shape, bump dataset version, run `validate_dataset.py` |
| Change an AI prompt | `backend/app/ai/provider.py` only; verify with `pytest` + a live call, and record the observed output in `MODEL-CONTRACTS.md` §7 |
| Add a setting | field in `AppSettings` + `copyWith` + setter + UI row; persistence needs its own scoped change |
| Fix a translation | correct the dataset/curated phrase DB, not the UI |

---

## 7. Verification loop (definition of done)

```powershell
$env:Path = "C:\Windows\System32;C:\Windows;C:\Program Files\Git\cmd;C:\flutter\bin;$env:Path"
cd trilingual_dictionary
flutter analyze            # must print "No issues found!"
flutter test               # must pass
cd backend
.venv\Scripts\python.exe -m pytest -q    # must pass
```

Before any migration or bulk write (not for ordinary code edits):

```powershell
.venv\Scripts\python.exe tools\preflight.py --intent "one line: what this run will change" --backup "path\to\before-copy"
.venv\Scripts\python.exe tools\check_encoding.py --db data\build\dictionary.sqlite   # when text columns are touched
```

Text repairs are two edits, never one. `dictionary.sqlite` is authoritative for
legacy Nepali, and `translations.db` keeps an import copy that
`tests/test_resolution.py` compares against:

```powershell
.venv\Scripts\python.exe tools\apply_ne_corrections.py                  # dry run, refuses on drift
.venv\Scripts\python.exe tools\apply_ne_corrections.py --apply --backup "path\to\before-copy"
.venv\Scripts\python.exe tools\sync_legacy_translation_text.py          # dry run
.venv\Scripts\python.exe tools\sync_legacy_translation_text.py --apply --backup "path\to\store-copy"
.venv\Scripts\python.exe tools\pack_asset.py                            # rebuild the shipped .gz
```

Each refuses to write unless the backup is byte-identical, the recorded `old`
value is still stored, and every unrelated row is unchanged afterwards. Re-running
is idempotent. `docs/DATA-REPAIR-2026-11-10.md` is a worked example.

Both print a JSON run-log and exit non-zero when the gate fails. `PROTOCOL.md`
explains which rule each one enforces.

Nothing is "done" until these pass. If your change touches an endpoint, also
exercise it (see `TESTING.md` §7) and paste the observed output in your report.

Do **not** claim a fix works because the command exited 0 — check the property
that matters (e.g. the Nepali column is non-empty, `degraded` is false).

---

## 8. Reporting format

End every change with:

1. **What changed** — files, one line each.
2. **Why** — the problem, not the implementation diary.
3. **Verified** — commands run + results (counts, status codes).
4. **Not verified / risks** — anything you could not run, plus known follow-ups.
5. **Docs touched** — which contract document you updated.

Keep it short. Do not paste whole files back to the user; summarise the diff.

---

## 9. Known defects (do not "rediscover" them)

Until fixed, treat these as documented, not as new findings:

- `DetailScreen` ignores the `?sense=` index passed by `ResultScreen`, so a
  multi-sense word always opens on its first sense.
- iOS on a physical device still needs an ATS exception for the LAN IP (only
  `localhost` / local networking is exempted).
- Backend reads the dataset JSON on every request (no cache).
- Favorites sync writes directly to Supabase from the app; the backend
  `/favorites` endpoints exist but the app does not use them.
- `GROQ_API_KEY` is empty; the legacy `AI_API_KEY` is used for Groq.
- CI (`.github/workflows/contracts.yml`) runs both suites plus the golden-vector,
  encoding and pin gates, but the full 96 MB dictionary is not built there, so the
  asset-level gates (encoding/`validate_fts` over the real DB) only run locally.
