# Trilingual Dictionary — Project Guide

Last updated: **2026-11-07** · Status: **working end-to-end on Windows** (Flutter app + FastAPI backend)

English / 简体中文 / नेपाली. You search or paste English **or** Chinese; the app returns
meanings and aligned example sentences in all three languages. Nepali is output-only.

---

## 1. Where everything lives

| Part | Path | Git |
|---|---|---|
| Flutter app | `C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary` | repo `github.com/pro-rider/trilingual_dictionary`, branch `main` |
| FastAPI backend | `C:\Users\Administrator\Desktop\Dictionery\backend` | **not a git repo yet** (untracked sibling folder) |

Toolchain on this machine (neither is on PATH by default):

```powershell
$env:Path = "C:\Windows\System32;C:\Windows;C:\Program Files\Git\cmd;C:\flutter\bin;$env:Path"
```

Flutter needs `git.exe` on PATH even to run `flutter analyze` — without it: *"Unable to find git in your PATH"*.

---

## 2. Run it

### Backend (FastAPI, port 8000)

```powershell
cd C:\Users\Administrator\Desktop\Dictionery\backend
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
cd ..\backend; .venv\Scripts\python.exe -m pytest -q      # 35 passed
cd ..\trilingual_dictionary; flutter analyze; flutter test # 0 issues, 11 passed
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
| `flutter test` | 11/11 passed |
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
| High | **Offline dataset is tiny** — `backend/data/seed/en_zh_ne.json` holds only 6 entries (`light, trade, mountain, water, book, teacher`). Without AI the dictionary is nearly empty. | Needs a real seed (~300–500 common words, human-reviewed Nepali). Don't ship AI-drafted Nepali as authoritative. |
| High | **Backend isn't under version control** | `backend/` sits beside the app repo with no `.git`. Start a repo (or add it to the app repo) before the next deploy. |
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
