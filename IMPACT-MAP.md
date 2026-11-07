# IMPACT-MAP.md — Change Impact & Dependency Map

Purpose: before you edit a file, know what else moves with it. Every row below was
derived from the actual import/call graph, not from intent.

Blast radius legend: **L** = 1–2 files, no user-visible behaviour change ·
**M** = one feature or one endpoint · **H** = multiple screens or the wire format.

---

## 1. Dependency direction

```
router ──▶ screens ──▶ providers ──▶ (ApiClient | DictionaryRepository | FavoritesRepository)
                                      │            │                    │
                                  backend API   assets JSON       SharedPreferences / Supabase
                                      │
                    ┌─────────────────┴──────────────────┐
                 services (search/sentence/quality)   text_analysis   ai
                    │                                     │            │
                 dataset JSON                       phrases/phrases DB  remote LLM
```

Rules that follow from this:

- **Screens never call HTTP or assets directly.** If you see `Dio` or `rootBundle`
  in `features/`, it is a mistake.
- **Providers are the only place where failures become `null`/empty state.**
- Backend never knows about Flutter models; the wire format is the seam.

---

## 2. Impact by change type

### 2.1 Dictionary data / models

| Change | Files that move | Tests | User-visible |
|---|---|---|---|
| Add an entry to `en_zh_ne.json` | `trilingual_dictionary/assets/data/en_zh_ne.json` **and** `backend/data/seed/en_zh_ne.json` (must stay byte-identical), `AppConstants.datasetVersion`, `backend DATASET_VERSION` | `tests/test_api.py` (search/popular counts), `test/widget_test.dart` (only if the normalizer changes) | new word searchable offline; **home "popular" list changes** (it is `first 6` of the asset, M) |
| Rename a field in `Sense` | Dart `lib/data/models/dictionary_entry.dart` (`fromJson`), `backend/app/schemas/search.py`, `services/dataset.py`, seed script, detail/result widgets, tests | both suites | blank column or missing chip (H) |
| Add a new sense field (optional) | pydantic schema + Dart model default + one widget row | backend test | additive, L |
| Change `sense_id` values | dataset + backend index + favorites stored ids become stale | — | saved favorites may no longer resolve (M) |
| Change Nepali status vocabulary | `models/dictionary_entry.dart` constants, `models/word.py` defaults, UI badges | `test_quality.py` | status labels wrong (M) |

**Trap:** `popularProvider` and `GET /popular` return *dataset order*, not usage
frequency. Prepending entries silently reorders the home screen.

### 2.2 Search behaviour

| Change | Files | Tests | Effect |
|---|---|---|---|
| Match strategy (exact→prefix→pinyin) | `lib/data/dictionary_repository.dart`, mirrored `backend/app/services/dataset.py` | `test_api.py::test_search_*`, `test/widget_test.dart` (Normalizer) | offline and online search disagree if only one is changed (H) |
| `SearchArgs` equality | `lib/features/search/search_provider.dart` + `resultProvider` | manual | removal ⇒ infinite spinner (H) |
| `offlineFirst` semantics | `settings_provider.dart`, `search_provider.dart` | — | offline users lose local hits (M) |
| Timeout | `lib/core/api_config.dart` | — | long AI searches/analysis abort early (M) |
| Add suggestions UI | `suggest` endpoint (exists), new provider, home screen | new tests | additive (M) |

### 2.3 Analysis / NLP

| Change | Files | Tests | Effect |
|---|---|---|---|
| Stopword list | `backend/app/text_analysis/analyzer.py` | `test_text_analysis.py` (stopword + degraded tests) | banner appears/disappears (M) |
| Segmenter (jieba params, split/merge) | `segmenter.py` | `test_text_analysis.py` (Chinese sentence test) | **expect `degraded` to change**; verify with a real sentence (H) |
| `SegmentKind` / `SegmentSource` enum | `schemas.py`, `analyzed_text.dart` (`isFunction`, `idioms`, `words`), `analyze_screen.dart` buckets | backend + manual | wrong bucket ⇒ cards vanish (H) |
| Prompt / JSON shape | `ai/provider.py` | `test_text_analysis.py` (AI cases), live call | silent blanks if keys drift (H) |
| `_MAX_AI_SURFACES` (60) | `text_analysis/analyzer.py` | live call | latency and truncation (M) |
| Failover order / thresholds | `ai/failover.py`, `config.py` | `test_failover.py` (8 cases) | availability/latency (M) |

### 2.4 Navigation / UI

| Change | Files | Tests | Effect |
|---|---|---|---|
| Add/rename a route | `lib/app/router.dart`, every `context.go/push` string (`splash`, `home`, `result`, `analyze`, `detail`, `history`, `settings`, `auth`, `favorites`) | manual | dead links (H) |
| Fix `FavoritesScreen` nav | `favorites_screen.dart` (`Navigator.pushNamed` → `context.push('/detail/<id>')`) | manual | favorites become tappable (L, high value) |
| Theme | `app_theme.dart`, `constants.dart`, every screen's literal `Color(0xFF…)` | manual (contrast at 1.4× text) | readability (H) |
| Settings row | `settings_provider.dart` (`AppSettings` + `copyWith` + setter) and `settings_screen.dart` | — | must add both or the control does nothing (M) |
| Text scale | `app.dart` (`textScaler`) | manual overflow check | clipped layout (M) |

### 2.5 Data / storage

| Change | Files | Tests | Effect |
|---|---|---|---|
| Persist settings | `settings_provider.dart` (+ `shared_preferences`), `main.dart` | new unit test | preferences survive restart (M) |
| Persist history | `history_provider.dart` | — | last searches survive (M) |
| Favorites storage | `favorites_repository.dart`, `favorites_provider.dart`, `favorites_screen.dart`, `settings_screen.dart` (count), `supabase_config.dart` | — | data loss if key or table changes (H) |
| Unify favorites on backend | app repo + `/favorites` endpoints + JWT plumbing | new tests | removes the two-writer divergence (H) |

### 2.6 Backend / infrastructure

| Change | Files | Tests | Effect |
|---|---|---|---|
| Route path or prefix | `backend/app/api/v1/*`, `api/router.py`, `main.py`, `lib/data/api_client.dart` | `test_api.py` | 404s in the app (H) |
| Response schema | `schemas/search.py` + Dart models | both suites | decode blanks (H) |
| Auth (JWT alg/secret) | `core/security.py`, `config.py`, tests, Supabase project settings | `test_auth.py` | 401/503 for all protected calls (H) |
| DB models / migrations | `models/*.py`, `alembic/versions/*`, `scripts/seed_database.py` | — | favorites/feedback 500; dictionary unaffected (M) |
| CORS | `config.py`, `main.py` | — | web client blocked (M) |
| Android manifest / Gradle | `android/app/src/main/AndroidManifest.xml`, `build.gradle.kts` | manual release build | release builds can/cannot reach the network (**H**) |
| iOS `Info.plist` | `ios/Runner/Info.plist` | manual | ATS blocks `http://` (H on iOS) |

---

## 3. Co-change matrix (edit one ⇒ check the other)

| Primary | Always check |
|---|---|
| `lib/data/models/*.dart` | `backend/app/schemas/search.py`, `services/dataset.py`, widgets using the field |
| `backend/app/schemas/search.py` | Dart models, `API-CONTRACTS.md` examples, `test_api.py` |
| `lib/core/constants.dart` | `app_theme.dart`, language chips, result/analyze cards |
| `lib/app/router.dart` | all `context.go/push` call sites, `FavoritesScreen` |
| `lib/features/search/*` | `analyze` screen (same query params), `home` routing rule |
| `backend/app/text_analysis/*` | `analyzed_text.dart`, `analyze_screen.dart`, `test_text_analysis.py` |
| `backend/app/ai/*` | `MODEL-CONTRACTS.md`, `test_failover.py`, `test_text_analysis.py` |
| any `.json` dataset | other copy + version constants + `DATA-GOVERNANCE.md` |
| `.env.example` | `config.py` defaults (they must match), `ENV-CONTRACTS.md` |

---

## 4. Tests to run per area

| Touched | Minimum verification |
|---|---|
| Dart model / repository | `flutter test` |
| Any screen | `flutter analyze` + manual route walk (home → result → detail → favorites) |
| Backend service/router | `pytest -q` |
| AI path | `pytest` **plus** a live `/analyze/text` call; confirm `degraded` and Nepali output |
| Dataset | hash comparison of both copies + a search for a changed word |
| Manifest/Gradle/Info.plist | build the affected target (`flutter build apk --release`) |

---

## 5. High-risk zones (get review before editing)

1. `backend/app/text_analysis/analyzer.py` — every user-visible quality signal
   (`degraded`, segment buckets) flows through it.
2. `lib/features/search/search_provider.dart` — family-key equality; one missing
   `==` breaks the result screen.
3. `backend/app/ai/failover.py` — availability for all AI features.
4. `lib/data/dictionary_repository.dart` — offline truth; drift from the backend
   matcher creates "works online, empty offline" reports.
5. `android/app/src/main/AndroidManifest.xml` and `ios/Runner/Info.plist` — a
   permission/ATS mistake only shows up in release or on device.
6. Any file touching `favorites` — two storage systems already disagree.
