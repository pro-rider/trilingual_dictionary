# Trilingual Dictionary — Project Guide

Last updated: **2026-11-08** · Status: **working end-to-end on Windows** (Flutter app + FastAPI backend + 123,672-entry SQLite dictionary, 2,477 HSK5-tagged entries + image pipeline)

English / 简体中文 / नेपाली. You search or paste English **or** Chinese; the app returns
meanings and aligned example sentences in all three languages. Nepali is output-only.

---

## 1. Where everything lives

| Part | Path | Git |
|---|---|---|
| Flutter app | `C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary` | repo `github.com/pro-rider/trilingual_dictionary`, branch `main` |
| FastAPI backend | `C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend` | tracked in this repo as `backend/` |

Toolchain on this machine (neither is on PATH by default):

```powershell
$env:Path = "C:\Windows\System32;C:\Windows;C:\Program Files\Git\cmd;C:\flutter\bin;$env:Path"
```

Flutter needs `git.exe` on PATH even to run `flutter analyze` — without it: *"Unable to find git in your PATH"*.

---

## 2. Run it

### Backend (FastAPI, port 8000)

```powershell
cd C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Swagger: http://127.0.0.1:8000/docs · Health: http://127.0.0.1:8000/api/v1/health

`.env` already contains keys for Gemini, OpenRouter and a legacy Groq (via `AI_API_KEY`);
`AI_ENABLED=true`, failover order `groq,gemini,openrouter`.

### App

```powershell
cd C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary
flutter run                                      # desktop/emulator
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000   # Android emulator → host backend
```

`lib/core/api_config.dart` defaults to `http://127.0.0.1:8000`; `127.0.0.1` on the
Android emulator is the emulator itself, hence the `10.0.2.2` override.

### Tests

```powershell
cd backend; .venv\Scripts\python.exe -m pytest -q      # 35 passed
cd ..\trilingual_dictionary; flutter analyze; flutter test # 0 issues, 16 passed
```

---

## 3. Architecture

### App (`lib/`)

| Layer | Files |
|---|---|
| App shell | `main.dart`, `app/app.dart`, `app/router.dart` (go_router: `/`, `/home`, `/result`, `/analyze`, `/detail/:id`, `/history`, `/settings`, `/auth`, `/favorites`) |
| Core | `core/normalizer.dart` (language detection + pinyin key), `api_config.dart`, `supabase_config.dart`, `constants.dart` |
| Data | `data/api_client.dart` (Dio, attaches Supabase JWT, **returns null instead of throwing** so offline mode takes over), `dictionary_repository.dart`, models |
| Features | `search` (home + result + cards), `analyze` (word/phrase/sentence view), `detail`, `history`, `favorites`, `auth`, `settings`, `onboarding`, `splash` |

Routing rule: a single word goes to `/result` (dictionary entry); anything with
punctuation, multiple tokens, or >4 Chinese characters goes to `/analyze`.

### Backend (`app/`)

`api/v1/*` routers → `services/*` (dataset, search, quality) → `text_analysis/*`
(segmenter → analyzer) → `ai/*` (provider facade → failover chain → providers).

`text_analysis` pipeline:

1. **Segment** — Latin words split on whitespace; Chinese split by **jieba**
   (`cut(HMM=False)`), then low-frequency n-gram merges are split back into real
   words (e.g. jieba's junk entry `今天天气` → `今天` + `天气`), then curated
   units (成语, compounds) are re-merged.
2. **Resolve offline** — curated phrase DB → dataset → dataset index.
3. **Resolve with AI** — all remaining units go in **one batched call** through
   the failover chain. Matching is case-insensitive, and if the model merges
   adjacent units (`很` + `好` → `很好`) that span is accepted.
4. **Assemble** — segments, `whole` translation, `degraded` flag.

Function words (`the`, `a`, `的`, `了` …) are emitted as `kind="function"`,
`source="stopword"`: shown in the text, never sent to the AI, never counted as a
failure. `degraded=true` now means a genuinely translatable unit is missing.

---

## 4. Verified state (2026-11-07)

| Check | Result |
|---|---|
| `flutter analyze` | No issues found |
| `flutter test` | 13/13 passed |
| `pytest` (backend) | 35/35 passed |
| `GET /api/v1/health` | `200 {"status":"ok","version":"0.1.0","dataset_version":1}` |
| `POST /api/v1/search` (`light`) | 2 senses, 3-language meanings + approved examples |
| `POST /api/v1/analyze` (English) | `The early bird catches the worm.` → 1 idiom + punctuation, `degraded=false`, Nepali correct |
| `POST /api/v1/analyze` (Chinese) | `今天天气很好，我们去公园散步。` → 今天 / 天气 / 很好 / 我们 / 去 / 公园 / 散步, `degraded=false` |
| Git | `main` in sync with `origin/main`, working tree clean |

### Fixed in this pass

1. **Chinese was split per character.** The offline lexicon had ~22 words, so
   `今天天气` became `今/天/天/气`. Now jieba segments properly; verified above.
2. **Case-sensitive AI matching.** `The` stayed unresolved while `the` got a
   meaning, because AI keys were matched exactly. Matching is now normalized.
3. **Idioms beaten by the stopword filter.** `a piece of cake` lost its first
   `a` to the function-word check; idiom matching now runs first.
4. **`degraded` cried wolf.** Determiners/prepositions produced *"some words
   could not be resolved"* banners on otherwise complete results.
5. **Model-merged units were dropped.** If the AI answered `很好` for `很`+`好`,
   the answer was thrown away; adjacent spans are now merged into one segment.
6. Added English proverbs (early bird / practice makes perfect / better late
   than never / actions speak louder than words) to the idiom DB.
7. `jieba>=0.42.1` added to `requirements.txt`.

### Fixed in the documentation pass

1. **Favorites tap failed** — `Navigator.pushNamed` replaced with `context.push`;
   covered by `test/favorites_navigation_test.dart`.
2. **Release build had no network** — `INTERNET` moved into the main manifest;
   cleartext allowed only in the debug manifest; iOS gets a `localhost` ATS
   exception. `flutter build apk --debug` verified.
3. **Settings/history reset on restart** — both now persist in
   `shared_preferences` (hydrate-on-build with a `ready` future);
   `test/settings_history_test.dart` covers save/load/clamp/cap.
4. The twelve project documents (`AGENTS.md` … `CONTRIBUTING.md`) were added.

---

## 5. Known gaps / next steps

| Priority | Gap | Notes |
|---|---|---|
| High | **Offline dataset is tiny** — the packaged asset `assets/data/en_zh_ne.json` holds only 6 entries. The 123,596-entry `backend/data/build/dictionary.sqlite` exists but is **not bundled in the app**, so offline search on a phone still finds 6 words. | Next step: ship the gzipped SQLite as an asset, copy it on first launch, query locally with sqflite. |
| ~~High~~ done | ~~Backend isn't under version control~~ | `backend/` now lives inside this repo and ships in the same commit history; `.env` and `.venv/` remain ignored. |
| Medium | Supabase auth unconfigured (`SUPABASE_URL` / `SUPABASE_JWT_SECRET` empty) | `/me`, favorites and feedback stay unauthenticated; sign-in screen can't complete. |
| Medium | No CI | `flutter analyze` + `flutter test` + `pytest` all pass locally; nothing enforces them on push. |
| Medium | `GROQ_API_KEY` empty, legacy `AI_API_KEY` used instead | Works today (`groq_api_key or ai_api_key`), but the naming is confusing — consolidate. |
| Low | "Learn" quick card is a placeholder (`SnackBar: later phase`) | Not implemented by design. |
| Low | `devtools_options.yaml` is untracked in the app repo | Commit or ignore it. |
| Low | `test/widget_test.dart` covers `Normalizer` only | No widget test for HomeScreen / AnalyzeScreen. |

---

## 6. Conventions

- AI output is always `ai_generated` / unreviewed; only content with
  `review_status: approved` (or curated phrase-DB entries) is treated as correct.
- The AI key never goes into the Flutter app — the backend proxies all calls.
- The API degrades instead of failing: missing data returns `null` / `degraded`
  and the UI falls back to offline mode.

---

## 7. Project structure — every folder and file

Repo root = `trilingual_dictionary/` (this directory **is** the git repo,
`github.com/pro-rider/trilingual_dictionary`, branch `main`). The Flutter app and
the FastAPI backend live in the same repo; `backend/` is not a submodule.

### 7.1 Top level

```
trilingual_dictionary/
├── lib/                 Flutter app source (all Dart code)
├── test/                Flutter tests (5 files)
├── assets/data/         Data bundled INTO the app
│   └── en_zh_ne.json    6 curated entries, the only offline dictionary today
├── backend/             FastAPI service + data tools (separate Python venv)
├── android/ ios/ windows/ macos/ linux/ web/   platform runners (mostly generated)
├── pubspec.yaml         Flutter deps (dio, riverpod, go_router, supabase, flutter_tts, …)
├── analysis_options.yaml  Dart lint rules — `flutter analyze` must stay at 0 issues
├── .gitignore           ignores build/, .dart_tool/, backend/.venv/, backend/data/
└── *.md                 the 13 contract documents + this guide (see 7.5)
```

Generated / never edited by hand: `build/`, `.dart_tool/`, `.idea/`,
`windows/flutter/ephemeral/`, `*/GeneratedPluginRegistrant.*` (regenerated by
`flutter pub get`), `pubspec.lock` (generated, but committed on purpose).

### 7.2 Flutter app — `lib/`

```
lib/
├── main.dart                     entry point: ProviderScope + runApp
├── app/
│   ├── app.dart                  MaterialApp.router, title, theme
│   ├── router.dart               ALL routes (go_router). Add a screen = edit here
│   └── theme/app_theme.dart      colors, text styles
├── core/
│   ├── api_config.dart           baseUrl (--dart-define=API_BASE_URL), 25 s timeout
│   ├── constants.dart            app-wide constants
│   ├── normalizer.dart           language detection (en/zh), pinyin key, search routing
│   ├── supabase_config.dart      anon key + schema notes for auth/favorites
│   ├── tts_service.dart          flutter_tts wrapper (en/zh voices, fallback to en)
│   └── errors/failures.dart      typed failures
├── data/
│   ├── api_client.dart           Dio client: search, suggest, sentence, analyze,
│   │                             images, health. Returns null on failure (never throws)
│   ├── providers.dart            Riverpod providers shared across features
│   ├── dictionary_repository.dart  curated JSON snapshot → bundled SQLite database
│   ├── local/offline_dictionary.dart  unpacks assets/data/dictionary.sqlite.gz once,
│   │                             then SQL search over 123,672 entries (read-only)
│   ├── auth_provider.dart        Supabase session state
│   └── models/                   dictionary_entry, sense, example_sentence,
│                                 analyzed_text, auth_state, signed_in_user, word_image
└── features/                     one folder per screen/flow
    ├── splash/splash_screen.dart
    ├── onboarding/onboarding_screen.dart
    ├── search/
    │   ├── home_screen.dart      search box, Favorites/History/Settings icons,
    │   │                         Recent + Popular chips, backend status footer
    │   ├── search_provider.dart  resultProvider(SearchArgs) — backend then asset
    │   ├── result_screen.dart    word header, sense selector, copy, TTS, image card
    │   └── widgets/              result_card, sense_selector, trilingual_block,
    │                             sentence_section, word_image_card
    ├── analyze/                  word/phrase/sentence/paragraph breakdown
    │   ├── analyze_screen.dart
    │   └── analyze_provider.dart
    ├── detail/detail_screen.dart full entry + zoomable image
    ├── history/                  history_provider, history_screen (persisted, max 20)
    ├── favorites/                favorites_repository (Supabase), favorites_screen
    ├── auth/auth_screen.dart
    └── settings/                 settings_screen, settings_provider (persisted)
```

**Where to change what**

| Want to change | Edit |
|---|---|
| Add/rename a screen or route | `lib/app/router.dart` + a new folder under `lib/features/` |
| Search behaviour, backend-vs-asset order | `lib/features/search/search_provider.dart` |
| What words exist offline / how a lookup matches | `lib/data/local/offline_dictionary.dart` |
| Result page layout, copy, TTS button | `lib/features/search/result_screen.dart` |
| Image card look (shimmer, zoom, attribution) | `lib/features/search/widgets/word_image_card.dart` |
| API host / timeout | `lib/core/api_config.dart` |
| English/Chinese auto-detection or routing rule | `lib/core/normalizer.dart` |
| Backend URL paths | `lib/data/api_client.dart` (must match `backend/app/api/v1/`) |
| Pronunciation behaviour | `lib/core/tts_service.dart` |
| Colors / typography | `lib/app/theme/app_theme.dart` |
| Offline dictionary size | `assets/data/en_zh_ne.json` (6 curated entries) + `assets/data/dictionary.sqlite.gz` (42.5 MB, rebuild via §8.7) |

### 7.3 Backend — `backend/`

```
backend/
├── .venv/                     Python 3.13 venv (gitignored). python.exe lives here
├── .env                       REAL secrets — gitignored, never commit
├── .env.example               template with placeholders
├── requirements.txt           pinned deps (fastapi, uvicorn, dio-side n/a, jieba, openai, …)
├── pyproject.toml / alembic.ini / docker-compose.yml
├── app/
│   ├── main.py                create_app(): CORS, /static/images mount, router, error handler
│   ├── core/
│   │   ├── config.py          ALL settings (dataset_path, dictionary_db_path,
│   │   │                      images_dir, image_base_url, AI keys, corpus)
│   │   ├── exceptions.py      ApiError → JSON envelope
│   │   └── security.py        JWT decode / Supabase auth helpers
│   ├── api/
│   │   ├── deps.py            shared dependencies (auth, db session)
│   │   └── v1/
│   │       ├── router.py      mounts every router under /api/v1 — add new one here
│   │       ├── search.py      POST /search
│   │       ├── suggest.py     GET /suggest
│   │       ├── sentence.py    POST /search/sentence
│   │       ├── popular.py     GET /popular
│   │       ├── analyze.py     POST /analyze/text
│   │       ├── images.py      GET /images, GET /images/batch  (image pipeline)
│   │       ├── health.py      GET /health
│   │       └── auth.py, favorites.py, feedback.py, providers.py
│   ├── schemas/               pydantic models (search.py, images.py)
│   ├── services/
│   │   ├── dataset.py         JSON fixture loader + index (6 curated entries)
│   │   ├── sqlite_dataset.py  123k-entry SQLite lookup: entry, suggest, stats
│   │   ├── search.py          lookup chain: fixture → SQLite → None
│   │   ├── sentence_generator.py, fallback_templates.py, quality.py
│   ├── text_analysis/         segmenter (jieba) → analyzer → phrases → schemas
│   ├── ai/                    base, failover (groq→gemini→openrouter), providers
│   ├── db/ models/            SQLAlchemy session + models (Postgres path, optional)
│   ├── utils/romanize_ne.py   Nepali romanization (search-by-Latin)
│   └── scripts/               seed_database.py, validate_dataset.py
├── tools/
│   ├── build_dictionary.py    CC-CEDICT → merged SQLite (entries/senses/FTS5/report)
│   └── fetch_images.py        Commons/Wikipedia → licence+quality gate → images tables
├── tests/                     pytest: api, auth, failover, quality, text_analysis (35)
└── data/                      GITIGNORED, machine-local, reproducible
    ├── raw/cedict.txt.gz      3.98 MB source dump
    ├── build/dictionary.sqlite  93.9 MB merged DB (+ .gz 42.6 MB, report.json)
    ├── seed/en_zh_ne.json     6 curated entries (also copied to assets/)
    └── images/                <sha1[0:2]>/<sha1>_800.jpg + _256.jpg, manifest.jsonl
```

**Where to change what**

| Want to change | Edit |
|---|---|
| New API endpoint | `backend/app/api/v1/<name>.py` + register in `router.py` |
| Response shape | `backend/app/schemas/*.py` (keep API-CONTRACTS.md in sync) |
| Env vars / defaults | `backend/app/core/config.py` (+ `.env.example`, ENV-CONTRACTS.md) |
| Lookup order (fixture/SQLite/AI) | `backend/app/services/search.py` |
| SQL of the big dictionary | `backend/app/services/sqlite_dataset.py` |
| Chinese segmentation | `backend/app/text_analysis/segmenter.py` |
| AI providers / failover order | `backend/app/ai/failover.py`, `.env` |
| Image licence rules or sources | `backend/tools/fetch_images.py` |
| Dictionary build rules (dedup, pinyin, categories) | `backend/tools/build_dictionary.py` |

### 7.4 Tests

```
test/
├── widget_test.dart              Normalizer unit tests
├── settings_history_test.dart    persistence: save / load / clamp / cap
├── favorites_navigation_test.dart tap a favorite → /detail route
└── tts_service_test.dart         TTS language mapping + fallback
backend/tests/
├── test_api.py                   9 endpoint tests incl. 3-language meanings
├── test_auth.py, test_failover.py, test_quality.py
└── test_text_analysis.py         Chinese segmentation + phrase resolution
```

Rule: a behaviour change without a test is not done. `flutter test` must stay green
(13 today), `pytest` must stay green (35 today), `flutter analyze` at 0 issues.

### 7.5 The documents — what each one is for

| File | Read it when | Update it when |
|---|---|---|
| `AGENTS.md` | you (or an AI agent) start editing code | rules for AI-assisted edits change |
| `ARCHITECTURE.md` | you need the layer/flow picture | a layer, flow or dependency changes |
| `API-CONTRACTS.md` | you touch an endpoint or its payload | endpoint/field added, renamed or removed |
| `ENV-CONTRACTS.md` | you add a setting or deploy | any env var or default changes |
| `DATA-GOVERNANCE.md` | you touch dictionaries, licences, dataset builds | data rules, sources, measured numbers change |
| `MODEL-CONTRACTS.md` | you touch AI calls or prompts | prompt/model/JSON contract changes |
| `IMPACT-MAP.md` | before a risky refactor ("what breaks?") | new cross-file dependency appears |
| `CHANGE-SCOPE.md` | deciding how far a change may go | boundaries change |
| `TESTING.md` | writing or fixing tests | test counts or strategy change |
| `PERFORMANCE-BUDGET.md` | something feels slow | budgets or measured latency change |
| `SECURITY.md` | secrets, auth, release | security rules change |
| `CONTRIBUTING.md` | setting up a new machine | setup steps/preconditions change |
| `project_guide.md` (this) | day-to-day "where is X, how do I run Y" | structure or workflows change |

### 7.6 Files that must never be committed

`.env` (real API keys), `.venv/`, `backend/data/raw/`, `backend/data/build/`,
`backend/data/images/`, `build/`, `.dart_tool/`. `.gitignore` already covers them —
if `git status --short` ever shows them, fix `.gitignore` before committing.

---

## 8. Maintenance recipes

### 8.1 Run the backend

```powershell
cd C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Must be started **from `backend/`** — `dataset_path`, `dictionary_db_path` and
`images_dir` in `config.py` are relative. Check: `Invoke-RestMethod
http://127.0.0.1:8000/api/v1/health`.

Restart after editing anything under `app/` (no `--reload` by default).

### 8.2 Run the app

```powershell
cd C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary
$env:Path = "$env:LOCALAPPDATA\Programs\nuget;C:\Windows\System32;C:\Windows;C:\Program Files\Git\cmd;C:\flutter\bin;$env:Path"
flutter run -d windows                                            # desktop
flutter run -d <device-id>                                        # phone (USB)
flutter run -d <device-id> --dart-define=API_BASE_URL=http://10.239.104.9:8000   # phone over Wi-Fi
```

**Phone over USB** (backend on this PC, app on the phone):

```powershell
adb reverse tcp:8000 tcp:8000     # phone's 127.0.0.1:8000 → this PC
adb reverse --list                # confirms: UsbFfs tcp:8000 tcp:8000
```

The tunnel dies whenever adb or USB reconnects — re-run it, then relaunch the app.
Build+install without `flutter run`: `flutter build apk --debug` then
`adb install -r build\app\outputs\flutter-apk\app-debug.apk`.

### 8.3 Rebuild the dictionary (adds words)

```powershell
cd ...\backend
# source dump (gitignored, download once):
#   https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz
.venv\Scripts\python.exe tools\build_dictionary.py --cedict data\raw\cedict.txt.gz --out data\build\dictionary.sqlite
```

Writes `dictionary.sqlite` (93.9 MB), `dictionary.sqlite.gz` (42.6 MB) and
`dictionary.report.json`. Restart the backend afterwards; `available()` is cached.

### 8.4 Fetch more images

```powershell
cd ...\backend
.venv\Scripts\python.exe tools\fetch_images.py --db data\build\dictionary.sqlite --limit 100
.venv\Scripts\python.exe tools\fetch_images.py --db data\build\dictionary.sqlite --category nature --limit 200
```

Resumable — words that already have an image are skipped. Read
`data\images\report.json` after every run: it lists accepted counts, licence
breakdown, and the `not_run` checks (watermark, NSFW, CLIP, pHash…). `--allow-commons`
turns on the unverified title-search tier; it produces wrong pictures and is
inspection-only.

### 8.5 Import the HSK5 word list (tag + Nepali gloss)

Input is the teacher-supplied `新HSK5词汇表（汉英）.pdf` (2,500 numbered words,
pinyin + characters, no English inside). The tool does **not** create duplicates:
every headword is already in CC-CEDICT, so it only sets `hsk_level = 5` and fills
`senses.gloss_ne`. Reentrant — it skips senses that already have Nepali.

```powershell
cd ...\backend
.venv\Scripts\python.exe tools\import_hsk5.py --pdf "<path to 新HSK5词汇表（汉英）.pdf>" --db data\build\dictionary.sqlite --dry-run
.venv\Scripts\python.exe tools\import_hsk5.py --pdf "<path>" --db data\build\dictionary.sqlite --batch 30 --threads 4
```

Measured: 2,499 records parsed (source has a duplicate number), 2,477 entries
tagged, 2,370 Nepali glosses, 313.8 s. `--all-senses` translates all 7,447 senses
instead of the primary one (≈2 h). Failures land in `hsk5_import.report.json`.

### 8.6 Extract words from an HSK5 past paper

The exam PDF is a **scan** — no text layer, and this machine has no `chi_sim`
OCR model. Transcribe the reading passages into `backend/data/exam/<paper>.txt`
first (plain text, one paragraph per line, options excluded). That directory is
gitignored — exam text is course material and is not published — so the tool
defaults to it but a fresh clone has to supply its own corpus. Then:

```powershell
cd ...\backend
.venv\Scripts\python.exe tools\import_exam_words.py --corpus data\exam\h51007_passages.txt --db data\build\dictionary.sqlite --dry-run
.venv\Scripts\python.exe tools\import_exam_words.py --corpus data\exam\h51007_passages.txt
```

jieba → keep ≥2-character CJK tokens → drop stop-words → match against the
dictionary (hits recorded in `corpus_hits`) → the leftovers go to the AI, which
also decides `is_word` so segmentation fragments (`要笔`, `画张`, `两天`) are
rejected instead of becoming bogus entries. Measured on `H51007.pdf`: 762 tokens,
634 hits, 128 missing, **76 new entries**, 43 fragments rejected, 346 Nepali
glosses, 86.7 s. Report: `exam_h51007.report.json`.

### 8.7 Bundle the offline dictionary into the APK

The whole database ships inside the app, so search works with the phone
airplane-mode'd. The asset is **not** committed (42.5 MB binary, and every
rebuild would add another blob) — regenerate it locally before building:

```powershell
cd ...\backend\data\build
.venv\Scripts\python.exe -c "import gzip,shutil; i=open('dictionary.sqlite','rb'); o=gzip.open('dictionary.sqlite.gz','wb',compresslevel=9); shutil.copyfileobj(i,o); o.close(); i.close()"
Copy-Item dictionary.sqlite.gz ...\trilingual_dictionary\assets\data\dictionary.sqlite.gz -Force

cd ...\trilingual_dictionary
flutter build apk --debug
adb reverse tcp:8000 tcp:8000
adb install -r build\app\outputs\flutter-apk\app-debug.apk
```

Measured: 96 MB → 42.5 MB in 31 s; APK 196 MB → 230.8 MB; first launch unpacks
in the background (`lib\data\local\offline_dictionary.dart`, `gzip.decode` inside
`Isolate.run`, written to `getApplicationSupportDirectory()/dictionary.sqlite`),
later launches reopen the file read-only with no work.

Search order on the phone: curated JSON snapshot (6 demo entries) →
`OfflineDictionary` (exact / traditional / prefix for 中文; tone-less pinyin, then
`match_score` over `gloss_en` for English) → backend API → AI. If the database
was rebuilt, the asset **must** be regenerated, or the phone keeps the old words.

### 8.8 Quality gate before any push

```powershell
cd ...\backend;  .venv\Scripts\python.exe -m pytest -q
cd ...;          flutter analyze
                 flutter test
```

### 8.9 Commit and push

```powershell
cd C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary
git status --short
git add -A
git -c user.name="pro-rider" -c user.email="pro-rider@users.noreply.github.com" commit -m "<type>(<area>): <what changed>"
git push origin main
```

Do not commit `backend/data/*`, `.env`, `.venv/`. If a doc describes behaviour
you changed, update that doc in the same commit (§7.5).

### 8.10 Common failures

| Symptom | Fix |
|---|---|
| App shows "Offline mode · backend not reachable" | backend not running, or `adb reverse` lost — run §8.1 then §8.2 tunnel |
| `No entry found` offline | expected: only 6 bundled entries (§5) |
| Backend 500 on `/search` | read `dictionary.report.json`; confirm `data/build/dictionary.sqlite` exists |
| `PathNotFoundException … errno = 2` on Windows build | plugin junction broken — recreate with `mklink /J` under `windows\flutter\ephemeral\.plugin_symlinks` |
| `LNK1168` on desktop build | old `trilingual_dictionary.exe` still running — stop it first |
| Images missing for a word | no approved image yet; `/images` returns `items: []` + icon by design |
