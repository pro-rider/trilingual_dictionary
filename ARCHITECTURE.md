# ARCHITECTURE.md — Trilingual Dictionary

Status: **v0.1.0**, working end-to-end on Windows. This document describes the code
that exists today, including where it deliberately differs from a textbook Clean
Architecture layout.

---

## 1. System overview

```
┌────────────────────────────┐        HTTP/JSON        ┌──────────────────────────────┐
│  Flutter app (lib/)        │  ───────────────────▶   │  FastAPI backend (backend/)   │
│                            │   http://127.0.0.1:8000 │                              │
│  UI (features/*)           │ ◀───────────────────    │  api/v1 → services →          │
│  State (Riverpod)          │      /api/v1/*          │  text_analysis / ai → data    │
│  Data (data/*, core/*)     │                         │                              │
│  assets/data/en_zh_ne.json │                         │  data/seed/en_zh_ne.json      │
└────────────────────────────┘                         └───────────────┬──────────────┘
        │  offline path (no backend needed)                           │
        └── bundled JSON ── DictionaryRepository                      ├─ LLM chain: Groq → Gemini → OpenRouter
                                                                      └─ Postgres (optional, favorites/feedback)
```

The app is **offline-first**: every screen renders without the backend. The
backend adds (a) words outside the bundled snapshot via AI, (b) whole-sentence
analysis, (c) reviewed example sentences, (d) account/favorites sync.

---

## 2. Flutter app

### 2.1 Layer map (as built)

| Layer | Location | Responsibility |
|---|---|---|
| Entry / shell | `lib/main.dart`, `lib/app/app.dart` | binding init, optional Supabase init, `ProviderScope`, `MaterialApp.router` |
| Navigation | `lib/app/router.dart` | `GoRouter` route table (`routerProvider`) |
| Theme | `lib/app/theme/app_theme.dart` | Material 3 light theme seeded from `LanguageColors.brand` |
| Presentation | `lib/features/<feature>/*_screen.dart`, `widgets/` | screens, cards, layout |
| State | `lib/features/*/*_provider.dart`, `lib/data/auth_provider.dart`, `lib/data/providers.dart` | Riverpod providers / notifiers |
| Data access | `lib/data/api_client.dart`, `dictionary_repository.dart`, `favorites_repository.dart` | HTTP (Dio), asset JSON, SharedPreferences, Supabase |
| Domain models | `lib/data/models/*.dart` | `DictionaryEntry`, `Sense`, `ExampleSentence`, `AnalyzedText`, `SignedInUser` |
| Cross-cutting | `lib/core/*` | normalizer, config, constants, failures |

**Deviation (intentional, documented):** there is **no separate `domain/` layer**
and **no use-case classes**. Repositories return `DictionaryEntry` / `AnalyzedText`
directly, and screens consume providers. Adding a domain layer now would be a
large refactor with no user-visible benefit; see `CHANGE-SCOPE.md` for the rules
before attempting it.

### 2.2 Startup sequence

```
main()
 ├─ WidgetsFlutterBinding.ensureInitialized()
 ├─ if SupabaseConfig.isConfigured → Supabase.initialize(url, publishableKey)
 └─ runApp(ProviderScope(child: TrilingualDictionaryApp()))
      └─ watch(settingsProvider) → themeMode, textScaler
      └─ watch(routerProvider)  → GoRouter
```

Supabase init is skipped entirely when `url`/`anonKey` are empty, so the offline
dictionary always boots. `SupabaseConfig.isConfigured` is also `false` on web
(`!kIsWeb`).

### 2.3 Navigation (GoRouter)

`initialLocation: '/'` → `SplashScreen` → `context.go('/home')` after 1400 ms.

| Path | Screen | Notes |
|---|---|---|
| `/` | `SplashScreen` | timed redirect |
| `/home` | `HomeScreen` | search box, language switch, popular, recent, backend status |
| `/onboarding` | `OnboardingScreen` | 3 slides; reachable but not forced |
| `/result?q=&lang=` | `ResultScreen` | `lang` = `english` \| `chinese` |
| `/analyze?q=&lang=` | `AnalyzeScreen` | same query params |
| `/detail/:entryId` | `DetailScreen` | `sense` query param accepted by caller, **ignored** by router |
| `/history` | `HistoryScreen` | in-memory list |
| `/settings` | `SettingsScreen` | preferences + account |
| `/auth` | `AuthScreen` | Supabase sign in/up |
| `/favorites` | `FavoritesScreen` | saved entry ids |

Route selection rule (`HomeScreen._shouldAnalyze`): punctuation, more than one
whitespace token, or more than 4 CJK characters ⇒ `/analyze`; otherwise `/result`.

### 2.4 Riverpod graph

```
settingsProvider (NotifierProvider<SettingsNotifier, AppSettings>)
    └── themeMode / textScale / uiLanguage / defaultInputLang / offlineFirst / soundEnabled
    └── read by: app.dart, resultProvider

dictionaryRepositoryProvider (Provider<DictionaryRepository>(rootBundle))
    ├── popularProvider (FutureProvider<List<DictionaryEntry>>, first 6)
    ├── resultProvider (FutureProvider.family<DictionaryEntry?, SearchArgs>)
    └── read directly by DetailScreen, FavoritesScreen

apiClientProvider (Provider<ApiClient>(Dio))
    ├── backendReachableProvider (FutureProvider<bool>)  → HomeScreen status dot
    ├── resultProvider (network leg)
    └── analyzeProvider (FutureProvider.family<AnalyzedText?, AnalyzeArgs>)

favoritesProvider (AsyncNotifierProvider<FavoritesRepository, List<String>>)
    ├── SharedPreferences key "favorites"
    └── Supabase table "favorites" (optional)

authUserProvider (StreamProvider<SignedInUser?>)   → SettingsScreen account tile
authControllerProvider (Provider<AuthController>)  → AuthScreen
historyProvider (NotifierProvider<HistoryNotifier, List<String>>)  → Home/History
routerProvider (Provider<GoRouter>)
```

**Family-key rule (important):** `SearchArgs` and `AnalyzeArgs` implement `==`
and `hashCode`. Without that, each rebuild creates a new family key and the
screen stays stuck on the loading spinner. Any new family argument class must do
the same.

### 2.5 Search pipeline (single word)

```
HomeScreen._submit(text)
 ├─ Normalizer.detectLanguage → InputLanguage
 ├─ historyProvider.add(text)
 └─ route: /result?q=…&lang=…

ResultScreen → resultProvider(SearchArgs(q, lang))
 ├─ if settings.offlineFirst:
 │    DictionaryRepository.search()  ── hit ──▶ DictionaryEntry
 │    else ApiClient.search()        ── hit ──▶ DictionaryEntry (may be AI-generated)
 └─ else (online-first):
      ApiClient.search()  → fallback DictionaryRepository.search()

DictionaryRepository.search order:
   english: exact word_en → prefix word_en
   chinese: exact word_zh → prefix word_zh → exact pinyin key (tone marks stripped)
   → never Nepali as input
```

Rendering: `ResultScreen` → `SenseSelector` (one chip per sense) → `ResultCard`
→ `TrilingualBlock` (EN/中文/नेपाली rows) → `SentenceSection` (first
`review_status == approved` example).

### 2.6 Analysis pipeline (sentence / paragraph)

```
AnalyzeScreen → analyzeProvider(AnalyzeArgs(q, lang)) → ApiClient.analyzeText()
  → backend POST /api/v1/analyze/text
  ← AnalyzedText { segments[], whole{}, degraded }
Rendering: idioms/phrases as highlighted cards, words as cards, unresolved as chips,
           "Whole translation" card, amber banner when degraded.
```

Analysis is **backend-only**: with the backend down the screen shows "Backend not
reachable" (there is no local segmentation in Dart).

### 2.7 Local storage

| Data | Store | Persistence |
|---|---|---|
| Favorites | `shared_preferences` list `favorites` (+ optional Supabase) | yes |
| Search history | `shared_preferences` list `history`, max 20, deduped | yes (user can clear) |
| Settings | `shared_preferences` keys `settings.*` | yes (loaded on first read) |
| Dictionary | `assets/data/en_zh_ne.json` (read-only bundle) | shipped asset |

Settings and history hydrate lazily: `build()` returns defaults/empty immediately,
then a disk read applies the stored values. Both notifiers expose `ready` for
tests; UI keeps watching the providers and rebuilds when hydration lands. A user
change made before hydration completes wins (`_dirty` guard).

### 2.8 Error strategy

- `ApiClient` catches `DioException` **and any other error**, returning `null`.
  Screens treat `null` as "not found / offline", not as a crash.
- `DictionaryRepository.load()` throws `DatasetLoadFailure` (a `Failure`) when the
  asset is missing/unreadable; it is otherwise idempotent (`_loaded` flag).
- `FavoritesRepository` swallows remote errors so local state always wins.
- `AnalyzeScreen` distinguishes "backend unreachable" from "no result".

---

## 3. Backend

### 3.1 Layer map

| Layer | Location | Responsibility |
|---|---|---|
| App factory | `app/main.py` | FastAPI, CORS, `/api/v1` mount, `ApiError` handler, `/` |
| Config | `app/core/config.py` | pydantic-settings from `.env` |
| Errors | `app/core/exceptions.py` | `ApiError(status_code, message)` → `{"detail": …}` |
| Auth | `app/core/security.py` | HS256 Supabase JWT verification |
| Routers | `app/api/v1/*.py` | one module per endpoint group |
| Services | `app/services/*` | dataset lookup, sentence generation, quality checks |
| Text analysis | `app/text_analysis/*` | segmenter → analyzer → schemas |
| AI | `app/ai/*` | provider facade, failover chain, concrete providers |
| Persistence | `app/db/*`, `app/models/*` | SQLAlchemy 2 models + session (favorites, feedback, word tables) |
| Data | `data/seed/en_zh_ne.json` | canonical v1 dictionary |
| Ops | `scripts/seed_database.py`, `alembic/`, `docker-compose.yml` | seeding, migrations, Postgres |

### 3.2 Request flow (search)

```
POST /api/v1/search
 → SearchRequest validation (q ≤ 80 chars, lang ∈ {en, zh})
 → services.search.dictionary_search_with_ai
      ├─ dataset.find_entry (exact → prefix, reads JSON each call)
      └─ if miss → ai.provider.generate_draft
             └─ FailoverLLMService.complete(prompt)
                  → groq → gemini → openrouter (retries + circuit breaker)
                  → _extract_json → SenseOut(source=ai)
 → SearchResponse(entry=None when both paths miss)
```

### 3.3 Request flow (analysis)

```
POST /api/v1/analyze/text
 → AnalyzeTextRequest (text ≤ 4000, lang ∈ {en, zh, auto})
 → text_analysis.analyzer.analyze_text
      ├─ tokenize (segmenter: jieba for CJK, whitespace for Latin)
      ├─ _build_segments: phrase DB → dataset index → stopwords(kind=function) → unresolved
      ├─ one batched AI call for all unresolved units (case-insensitive match)
      ├─ _merge_ai_spans: accept spans the model merged (很+好 → 很好)
      └─ degraded = any content unit still unresolved
 → AnalyzeTextResponse
```

The first Chinese analysis in a process pays a one-off **~390 ms jieba dictionary
load**; subsequent calls reuse it.

### 3.4 Data source of truth

v1 reads `data/seed/en_zh_ne.json` on **every** lookup (no cache). Postgres models
exist (`words`, `senses`, `example_sentences`, `favorites`, `feedback`) and
`scripts/seed_database.py` can load them, but **no endpoint reads Postgres for
dictionary data yet** — only favorites/feedback use the DB.

The app's `assets/data/en_zh_ne.json` is byte-identical to the backend seed
(verified hash `1C0DD349…1F89`). Any dataset change must update **both** copies
and bump `AppConstants.datasetVersion` / `DATASET_VERSION`.

### 3.5 Degradation rules

| Condition | Behaviour |
|---|---|
| Word not in dataset, AI enabled and working | entry with `sense.meaning_ne_status = ai_generated`, `example.review_status = ai_generated` |
| Word not in dataset, AI down | `entry: null`, HTTP 200 |
| Analysis: some units unresolved | `degraded: true`, blanks kept |
| Analysis: all providers down | `degraded: true`, `whole` omitted |
| Supabase not configured | `/me`, favorites, feedback → **503** |
| Postgres not running | favorites/feedback → 500; search/analyze unaffected |

---

## 4. Cross-cutting conventions

- **Three languages, fixed.** English and Chinese are input; Nepali is output-only.
- **Color identity:** EN = sky `#0EA5E9`, 中文 = rose `#E11D48`, नेपाली = amber `#D97706`
  (`lib/core/constants.dart`). Never hardcode a fourth palette.
- **Theme:** light only; `ThemeMode.dark` currently maps to the light theme
  (`darkTheme: AppTheme.light`) — dark mode is a later phase.
- **Text scaling:** `MediaQuery.textScaler` multiplied by `settings.textScale`
  (0.8–1.4). Layouts must survive 1.4× without overflow.
- **Backend contract:** every new field is additive and optional; old clients must
  keep working.

---

## 5. Known architectural gaps

1. **No domain/use-case layer** — documented deviation, not a target.
2. **Dictionary JSON is read per request** — fine at 6 entries, must be cached
   before the dataset grows past ~1k entries.
3. **Favorites are written from two places** — the app talks to the Supabase
   table directly; the backend `/favorites` endpoints use Postgres. They can
   diverge.
4. **No pagination / rate limiting / request IDs** anywhere in the API.
5. **Postgres dictionary path is unimplemented** even though models and a seeder
   exist.
6. **Selected sense is lost on navigation.** `ResultScreen` pushes
   `/detail/<id>?sense=<index>`, but `DetailScreen` only receives `entryId`, so
   tapping the second sense of `light` opens the detail view on sense 0.
7. **iOS on a physical device** still needs an ATS exception for the LAN IP
   (the `Info.plist` exception covers `localhost` / local networking only).

Fixed in the current build: persistence of settings and history; favorites
navigation (`context.push`); `INTERNET` permission in the release manifest with
debug-only cleartext.

