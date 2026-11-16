# Trilingual Dictionary — Project Guide

Last updated: **2026-11-08** · Status: **working end-to-end on Windows** (Flutter app + FastAPI backend + 123,672-entry SQLite dictionary, 2,477 HSK5-tagged entries + image pipeline)

English / 简体中文 / नेपाली. You search or paste English **or** Chinese; the app returns
meanings and aligned example sentences in all three languages. Nepali is output-only.

---

## 1. Where everything lives

| Part | Path | Git |
|---|---|---|
| Flutter app | repository root | repo `github.com/pro-rider/trilingual_dictionary`, branch `main` |
| FastAPI backend | `backend/` | tracked in this repo as `backend/` |

Toolchain on this machine (neither is on PATH by default):

```powershell
$env:Path = "C:\Windows\System32;C:\Windows;C:\Program Files\Git\cmd;C:\flutter\bin;$env:Path"
```

Flutter needs `git.exe` on PATH even to run `flutter analyze` — without it: *"Unable to find git in your PATH"*.

---

## 2. Run it

### Backend (FastAPI, port 8000)

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Swagger: http://127.0.0.1:8000/docs · Health: http://127.0.0.1:8000/api/v1/health

`.env` already contains keys for Gemini, OpenRouter and a legacy Groq (via `AI_API_KEY`);
`AI_ENABLED=true`, failover order `groq,gemini,openrouter`.

### App

```powershell
cd trilingual_dictionary
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

## 4. Verified state (2026-11-08)

| Check | Result |
|---|---|
| `flutter analyze` | No issues found |
| `flutter test` | 19/19 passed |
| `pytest` (backend) | 42/42 passed |
| `GET /api/v1/health` | `200 {"status":"ok","version":"0.1.0","dataset_version":1}` |
| `POST /api/v1/dictionary/enrich` | `200`, Nepali + one trilingual sentence per sense (20 senses/call) |
| English lookup (backend) | `water→水`, `book→书`, `apple→苹果`, `fire→火`, `behaviors→行为`, `Nepal→尼泊尔`, `China→中国` |
| Dictionary self-check | `tools/audit_roundtrip.py`: 2,273 HSK5 queries, 1,584 exact (69.7%) |
| On the phone (SM-M166P, Android 16) | `Nepal` → नेपाली "हिमालयको देश" + 3-language sentence; `China` → 中国 + sentence; `teacher` → 老师 / शिक्षक + reviewed sentence |
| Bundled asset | `assets/data/dictionary.sqlite.gz` 43.3 MB = 123,672 entries; APK 248.4 MB |
| Git | `main` in sync with `origin/main` |

### 4.1 Verified state (2026-11-07)

| Check | Result |
|---|---|
| `flutter analyze` | No issues found |
| `flutter test` | 13/13 passed |
| `pytest` (backend) | 35/35 passed |
| `POST /api/v1/search` (`light`) | 2 senses, 3-language meanings + approved examples |
| `POST /api/v1/analyze` (English) | `The early bird catches the worm.` → 1 idiom + punctuation, `degraded=false`, Nepali correct |
| `POST /api/v1/analyze` (Chinese) | `今天天气很好，我们去公园散步。` → 今天 / 天气 / 很好 / 我们 / 去 / 公园 / 散步, `degraded=false` |

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
| ~~High~~ done | ~~Offline dataset is tiny~~ | The whole 123,672-entry database now ships as `assets/data/dictionary.sqlite.gz` (§8.7); offline search finds every word. |
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
├── test/                Flutter tests (6 files, 19 tests)
├── assets/data/         Data bundled INTO the app
│   ├── en_zh_ne.json    6 curated demo entries (first hit in the search chain)
│   └── dictionary.sqlite.gz   the WHOLE 123,672-entry database, gzipped (43.3 MB,
│                         gitignored — regenerate locally, §8.7)
├── backend/             FastAPI service + data tools (separate Python venv)
├── android/ ios/ windows/ macos/ linux/ web/   platform runners (mostly generated)
├── pubspec.yaml         Flutter deps (dio, riverpod, go_router, supabase, flutter_tts, …)
├── analysis_options.yaml  Dart lint rules — `flutter analyze` must stay at 0 issues
├── .gitignore           ignores build/, .dart_tool/, backend/.venv/, backend/data/,
│                        and assets/data/dictionary.sqlite.gz
└── *.md                 the 12 contract documents + this guide (see 7.5)
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
│   ├── tts_service.dart          flutter_tts wrapper (en / zh / ne, fallback ne→hi→en)
│   └── errors/failures.dart      typed failures
├── data/
│   ├── api_client.dart           Dio client: search, suggest, sentence, analyze,
│   │                             images, health, enrich. Returns null on failure (never throws)
│   ├── providers.dart            Riverpod providers shared across features
│   ├── dictionary_repository.dart  curated JSON snapshot → bundled SQLite database
│   ├── local/offline_dictionary.dart  unpacks assets/data/dictionary.sqlite.gz once,
│   │                             then SQL search over 123,672 entries; enrich() writes
│   │                             missing Nepali + examples back into that file.
│   │                             `assetVersion` string + `<db>.stamp` sidecar decide
│   │                             whether the bundled copy must be re-unpacked
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
| Per-language speaker buttons (EN / 中文 / नेपाली + sentences) | `lib/features/search/widgets/trilingual_block.dart` |
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
│   │       ├── dictionary.py  POST /dictionary/enrich  (Nepali + example, on demand)
│   │       ├── health.py      GET /health
│   │       └── auth.py, favorites.py, feedback.py, providers.py
│   ├── schemas/               pydantic models (search.py, images.py, dictionary.py)
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
│   ├── enrich_dictionary.py   fills empty gloss_ne + examples (resumable, rate-limited)
│   ├── import_hsk5.py         HSK5 list → hsk_level + Nepali gloss
│   ├── import_exam_words.py   HSK5 past paper → missing words into the database
│   ├── add_frequency.py       wordfreq → entries.freq_rank (how common the word really is)
│   ├── reorder_senses.py      demotes surname / abbr. / variant / brand senses so
│   │                          sense 0 is the real meaning (idempotent)
│   ├── audit_roundtrip.py     self-check: every HSK5 word must find itself again
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
├── tts_service_test.dart         TTS language mapping + fallback
├── trilingual_speakers_test.dart one speaker per language row (EN/中文/नेपाली),
│                                  and the empty-row "Translate now" action
└── offline_dictionary_test.dart  real 123k-entry database, opened read-write through
                                  `OfflineDictionary(overridePath: …)`:
                                  7 tests — raisin/葡萄干/Kishmish, 安排 has Nepali,
                                  pinyin, Nepal→尼泊尔, China→中国,
                                  behaviors→行为 (behaviour/behavior present),
                                  enrichment is a no-op when the backend is down
backend/tests/
├── test_api.py                   9 endpoint tests incl. 3-language meanings
├── test_auth.py, test_failover.py, test_quality.py
├── test_english_lookup.py        English ranking: water/书/apple/fire/behaviors
└── test_text_analysis.py         Chinese segmentation + phrase resolution
```

Rule: a behaviour change without a test is not done. `flutter test` must stay green
(**19 today**), `pytest` must stay green (**42 today**), `flutter analyze` at 0 issues.

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
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Must be started **from `backend/`** — `dataset_path`, `dictionary_db_path` and
`images_dir` in `config.py` are relative. Check: `Invoke-RestMethod
http://127.0.0.1:8000/api/v1/health`.

Restart after editing anything under `app/` (no `--reload` by default).

### 8.2 Run the app

```powershell
cd trilingual_dictionary
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
cd ...\backend
.venv\Scripts\python.exe -c "import gzip,shutil,sqlite3; db=r'data/build/dictionary.sqlite'; c=sqlite3.connect(db); c.execute('VACUUM'); c.close(); i=open(db,'rb'); o=gzip.open('dictionary.sqlite.gz','wb',compresslevel=9); shutil.copyfileobj(i,o); o.close(); i.close()"
Copy-Item data\build\dictionary.sqlite.gz ...\trilingual_dictionary\assets\data\dictionary.sqlite.gz -Force

cd ...\trilingual_dictionary
# 1. bump OfflineDictionary.assetVersion in lib\data\local\offline_dictionary.dart
flutter build apk --debug
adb reverse tcp:8000 tcp:8000
adb install -r build\app\outputs\flutter-apk\app-debug.apk
```

Measured: 96 MB → **43.3 MB** in ~90 s (incl. `VACUUM`); APK **248.4 MB**;
first launch unpacks in the background
(`lib\data\local\offline_dictionary.dart`, `gzip.decode` inside `Isolate.run`,
written to `getApplicationSupportDirectory()/dictionary.sqlite`), later launches
reopen the file (read-write, because enrichment writes into it). First-run unpack
of 43 MB takes ~30 s on the test phone — the UI shows a spinner meanwhile.

Search order on the phone: curated JSON snapshot (6 demo entries) →
`OfflineDictionary` (exact / traditional / prefix for 中文; tone-less pinyin, then
`_bestEnglishRow` for English, which scores only the definition part of
`gloss_en`, tries singular/plural forms, and refuses a match that sits inside a
parenthetical) → on-demand enrichment (below) → backend API → AI.

**If the asset is rebuilt without bumping `assetVersion`, the phone keeps the
old words forever** — it is holding its own copy, not the APK's. See §9.2.

### 8.8 Fill Nepali glosses and example sentences

CC-CEDICT has no Nepali and no example sentences, so most words open with an
empty नेपाली box and no sentence. Two ways to fill them:

**(a) Live, per lookup — already automatic.** With the backend reachable, the
app sends the senses it is about to show (`POST /api/v1/dictionary/enrich`),
writes the answer into its own database, and re-renders. The first lookup of a
word needs the network; every later lookup of the same word works offline.

**(b) Bulk, into the SQLite file** (so the shipped asset is pre-filled):

```powershell
cd ...\backend
$env:PYTHONPATH=(Get-Location).Path
.venv\Scripts\python.exe tools\enrich_dictionary.py --db data\build\dictionary.sqlite --dry-run
# HSK5 first — it is what the student actually studies (2,477 senses, ~90 min):
.venv\Scripts\python.exe tools\enrich_dictionary.py --db data\build\dictionary.sqlite `
  --hsk-only --primary-only --batch 25 --threads 5
# then everything else, if you have the time:
.venv\Scripts\python.exe tools\enrich_dictionary.py --db data\build\dictionary.sqlite `
  --primary-only --batch 25 --threads 6
```

`--hsk-only` restricts the run to `hsk_level = 5`; `--primary-only` to sense 0.
The selection is "Nepali missing **or** sentence missing", so re-running continues
where it stopped. Measured **0.5 senses/s** (Gemini HTTP 429 and groq empty
responses are the ceiling; the failover chain still completes the batch). Result
on 2026-11-08: **HSK5 2,477/2,477 primary senses have Nepali + one trilingual
sentence** (123 done in 262.8 s, then the remaining 2,354 backfilled). Report:
`data\build\hsk5.examples.report.json`.

### 8.9 Quality gate before any push

```powershell
cd ...\backend;  .venv\Scripts\python.exe -m pytest -q
cd ...;          flutter analyze
                 flutter test
```

### 8.10 Commit and push

```powershell
cd trilingual_dictionary
git status --short
git add -A
git -c user.name="pro-rider" -c user.email="pro-rider@users.noreply.github.com" commit -m "<type>(<area>): <what changed>"
git push origin main
```

Do not commit `backend/data/*`, `.env`, `.venv/`. If a doc describes behaviour
you changed, update that doc in the same commit (§7.5).

### 8.11 Common failures

| Symptom | Fix |
|---|---|
| App shows "Offline mode · backend not reachable" | backend not running, or `adb reverse` lost — run §8.1 then §8.2 tunnel |
| A new word still shows the OLD meaning after a rebuild | `OfflineDictionary.assetVersion` was not bumped — see §9.2 |
| Backend 500 on `/search` | read `dictionary.report.json`; confirm `data/build/dictionary.sqlite` exists |
| `PathNotFoundException … errno = 2` on Windows build | plugin junction broken — recreate with `mklink /J` under `windows\flutter\ephemeral\.plugin_symlinks` |
| `LNK1168` on desktop build | old `trilingual_dictionary.exe` still running — stop it first |
| Images missing for a word | no approved image yet; `/images` returns `items: []` + icon by design |
| `adb devices` empty while the phone is plugged in | `adb kill-server; adb start-server`; if still empty, re-plug the cable |

---

## 9. Maintenance runbook — "I changed X, what do I run?"

Everything is generated from `backend/data/build/dictionary.sqlite`. **Nothing in
`backend/data/` is in git**, so a fresh clone has to rebuild it (§8.3) and then
replay §9.1 in order.

### 9.1 Rebuild order (after `build_dictionary.py`)

| # | Command (from `backend/`) | What it adds | Measured |
|---|---|---|---|
| 1 | `tools\import_hsk5.py --pdf "<新HSK5词汇表.pdf>"` | `hsk_level=5` + Nepali for 2,477 words | 313.8 s |
| 2 | `tools\import_exam_words.py --corpus data\exam\h51007_passages.txt` | past-paper words missing from HSK5 (76 new) | 86.7 s |
| 3 | `tools\add_frequency.py` | `entries.freq_rank` from `wordfreq` — decides which of two valid words wins | 3.8 s |
| 4 | `tools\reorder_senses.py` | moves surname / abbr. / variant / brand senses to the end | 1,353 entries |
| 5 | `tools\enrich_dictionary.py --primary-only` (optional, slow) | Nepali + example sentences baked into the file | 0.4 senses/s |
| 6 | gzip + copy to `assets\data\` (§8.7) | ships the new data in the APK | 31 s |
| 7 | bump `assetVersion` (§9.2) | makes the phone accept the new file | — |
| 8 | `flutter build apk --debug` + `adb install -r` | | 23 s |

`build_dictionary.py` wipes `ai_cache`, `corpus_hits`, `hsk_level`, `gloss_ne`,
`examples`, `freq_rank` and the sense order — that is why steps 1–4 exist and why
they must be run again after every rebuild.

### 9.2 The version stamp — the one rule you must not forget

The phone writes Nepali glosses and sentences into **its own copy** of the
database, so it cannot simply re-read the APK asset. Each install is compared
against `OfflineDictionary.assetVersion`
(`lib\data\local\offline_dictionary.dart`) and a sidecar
`<app support dir>\dictionary.sqlite.stamp`:

* constant matches stamp → open the existing file (keeps everything enriched)
* constant missing/mismatched → delete the file, unpack the bundled asset again

**Every time you regenerate `assets/data/dictionary.sqlite.gz`, change that
string** (e.g. `'2026-11-08.3'` → `'2026-11-09.1'`). Otherwise the APK ships new
data that the phone never opens.

### 9.3 "A word shows the wrong meaning" — the diagnosis path

1. Reproduce **in the database, not on the phone**:
   ```powershell
   cd ...\backend; $env:PYTHONPATH=(Get-Location).Path
   .venv\Scripts\python.exe -c "from app.services import sqlite_dataset as sd; print(sd.find_entry('water','en'))"
   ```
   `test\offline_dictionary_test.dart` does the same through the Dart code path.
2. See what the database actually holds for that word:
   ```sql
   SELECT e.entry_id, e.freq_rank, e.is_proper, s.sense_order, s.gloss_en, s.gloss_ne
   FROM entries e JOIN senses s ON s.entry_id = e.entry_id
   WHERE e.simplified = '<汉字>' ORDER BY s.sense_order;
   ```
3. Three usual causes and their fix:

| Cause | Symptom | Fix |
|---|---|---|
| A non-lexical sense is first | opens on `surname X` / `abbr. for X` | `tools\reorder_senses.py` (idempotent) |
| A rarer word outranks the common one | `fire` → 发射 instead of 火 | `tools\add_frequency.py` (fills `freq_rank`) |
| The match sits inside a parenthetical | `Nepal` → “Nepal fulvetta” | scoring in `_gloss_score` / `_glossScore` — it must never read inside brackets |

4. After a **database** fix: §9.1 steps 6–8 (repack, bump, reinstall).
   After a **scoring** fix (Dart/Python only): just rebuild the APK.

### 9.4 Measuring dictionary quality

```powershell
cd ...\backend
$env:PYTHONPATH=(Get-Location).Path
.venv\Scripts\python.exe tools\audit_roundtrip.py
```

It takes each HSK5 word's own first English gloss as a query and checks the
lookup returns that same word: **2,273 queries, 1,584 exact (69.7%), 689
mismatches** on 2026-11-08 (report `data\build\audit.roundtrip.json`). Most
mismatches are legitimate synonyms (`one` → 一个, `before` → 之前), which is why
the number is a *regression gauge*, not a pass/fail gate: it must not go down.

Coverage today (`dictionary.sqlite`, 2026-11-08):

| Field | Filled | Total |
|---|---|---|
| entries | 123,672 | — |
| senses | 198,306 | — |
| HSK5 primary senses with Nepali | **2,477 / 2,477 (100 %)** | 2,477 |
| `gloss_ne` (all senses) | 3,230 | 198,306 |
| `examples` rows | 327 → growing (HSK5 backfill job) | — |
| `freq_rank` | 116,533 | 123,672 |
| `gloss_zh` | 0 (renders as the headword instead) | 198,306 |

To finish the HSK5 sentence backfill (≈2,354 senses, ~0.5 senses/s ≈ 75 min):

```powershell
cd ...\backend
$env:PYTHONPATH=(Get-Location).Path
.venv\Scripts\python.exe tools\enrich_dictionary.py --db data\build\dictionary.sqlite `
  --hsk-only --primary-only --batch 25 --threads 5 --report data\build\hsk5.examples.report.json
```

It is resumable and skips senses that already have a sentence, so re-running it
just continues where it stopped. When it finishes: §9.1 steps 6–8.

Beyond HSK5, Nepali and example sentences are **filled on demand** (first lookup
while online writes them into the phone's database, §8.8a) rather than
pre-generated — pre-generating all 195k senses at 0.5 senses/s is ≈4.5 days on
free-tier keys.
