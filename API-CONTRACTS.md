# API-CONTRACTS.md — Interfaces & Integration Contracts

Base URL (dev): `http://127.0.0.1:8000` · API prefix `/api/v1` · JSON only
(`Content-Type: application/json`) · charset UTF‑8, Nepali in Devanagari.

Version compatibility: the path segment `/api/v1` is the contract boundary.
**Additive changes only** — new optional fields may appear at any time, existing
fields may not be renamed, retyped, or removed. Clients must ignore unknown keys
(the Dart models read fields by name and default to `''`).

There is **no pagination, no rate limiting, no request-id header, no ETag, and no
server-side timeout middleware** in v1.

---

## 1. Endpoint index

| Method | Path | Auth | Response model | Caller |
|---|---|---|---|---|
| GET | `/` | — | `{app, version}` | humans / smoke test |
| GET | `/api/v1/health` | — | `{status, version, dataset_version}` | `ApiClient.isReachable()` |
| GET | `/api/v1/providers` | — | failover health | ops / debugging |
| POST | `/api/v1/search` | — | `SearchResponse` | `ApiClient.search()` |
| POST | `/api/v1/analyze/text` | — | `AnalyzeTextResponse` | `ApiClient.analyzeText()` |
| POST | `/api/v1/search/sentence` | — | `SentenceResponse` | **not used by the app yet** |
| GET | `/api/v1/popular` | — | `{words: string[]}` | **not used by the app** (app uses its own 6 local entries) |
| GET | `/api/v1/suggest` | — | `{suggestions: string[]}` | **not used by the app** |
| GET | `/api/v1/me` | Bearer | `{uid, email}` | **not used by the app** |
| GET | `/api/v1/favorites` | Bearer | `{entry_ids: string[]}` | **not used by the app** (app talks to Supabase directly) |
| POST | `/api/v1/favorites` | Bearer | `{entry_ids: string[]}` | not used by the app |
| DELETE | `/api/v1/favorites/{entry_id}` | Bearer | `{entry_ids: string[]}` | not used by the app |
| POST | `/api/v1/feedback` | Bearer | `{id, status}` | not used by the app |

"Not used by the app" still counts: external clients and future screens depend on
these shapes, so they are contracts, not dead code.

---

## 2. Error contract

| Status | When | Body |
|---|---|---|
| 400 | `ApiError` raised explicitly, or unhandled validation path | `{"detail": "<message>"}` |
| 401 | missing header / not `Bearer …` / bad signature / missing `sub` | `{"detail": "Missing bearer token"}` etc. |
| 422 | pydantic validation failure (bad JSON shape, too long, wrong enum) | FastAPI's standard `{"detail": [{"loc": …, "msg": …, "type": …}]}` |
| 503 | `SUPABASE_JWT_SECRET` empty on a protected route | `{"detail": "Auth not configured"}` |
| 500 | unexpected exception (e.g. dataset file missing, DB down) | FastAPI default 500 (no JSON body guarantee) |

**Client behaviour:** `ApiClient` catches `DioException` **and any `catch (_)`**,
returning `null`. A 422/500 is therefore indistinguishable from "offline" in the
UI. Do not build logic that depends on HTTP status codes from the app side unless
you also change this contract.

---

## 3. `GET /api/v1/health`

```json
{"status": "ok", "version": "0.1.0", "dataset_version": 1}
```

No dependencies are probed: AI and Postgres can both be down and this still
returns 200. The app's home-screen dot therefore means "the process is up", not
"AI works". Use `/api/v1/providers` for AI health.

---

## 4. `GET /api/v1/providers`

```json
{
  "ai_enabled": true,
  "chain": ["groq", "gemini", "openrouter"],
  "active": ["gemini", "openrouter"],
  "max_retries": 1,
  "providers": {
    "groq": {
      "enabled": true, "active": false, "model": "openai/gpt-oss-120b",
      "timeout": 40, "circuit_open": false,
      "success_count": 0, "failure_count": 0, "consecutive_failures": 0,
      "avg_latency_ms": 0.0, "last_latency_ms": 0.0, "last_error": ""
    }
  },
  "all_down": false
}
```

`active` excludes providers that are disabled or keyless. Metrics are per-process
and reset on restart.

---

## 5. `POST /api/v1/search` — single word

**Request**

```json
{"q": "light", "lang": "en"}
```

| Field | Type | Rules |
|---|---|---|
| `q` | string | required, 1–80 chars, trimmed server-side, case-insensitive |
| `lang` | `"en"` \| `"zh"` | default `"en"`; Nepali is **not** accepted |

**Response**

```json
{
  "query": "light",
  "lang": "en",
  "entry": {
    "entry_id": "light",
    "word_en": "light",
    "word_zh": "光",
    "senses": [{
      "sense_id": "light_noun_illumination",
      "word_en": "light",
      "word_zh": "光",
      "pinyin": "guāng",
      "ipa_en": "/laɪt/",
      "part_of_speech": "noun",
      "meaning_en": "Illumination that makes things visible",
      "meaning_zh": "使物体可见的光",
      "meaning_ne": "प्रकाश",
      "meaning_ne_status": "published",
      "examples": [{
        "en": "The light is bright.",
        "zh": "灯光很亮。",
        "ne": "बत्तीको प्रकाश उज्यालो छ।",
        "source": "reviewed",
        "review_status": "approved"
      }]
    }]
  }
}
```

| Case | Result |
|---|---|
| Exact/prefix match in dataset | `entry` from the JSON, `meaning_ne_status: "published"` |
| Miss, AI enabled + success | AI entry: `entry_id` starts with `ai-`, `meaning_ne_status: "ai_generated"`, `example.review_status: "ai_generated"` |
| Miss, AI off/failed | `{"query": …, "lang": …, "entry": null}` — **HTTP 200**, not 404 |
| DB down | unaffected (search never touches Postgres) |
| Dataset file missing | 500 |

Matching order: exact → prefix. `zh` matches `senses[].word_zh` first, then
`word_zh` prefix. The response always collapses to one `entry`; multiple senses
of that word are all included.

---

## 6. `POST /api/v1/analyze/text` — word / phrase / sentence / paragraph

**Request**

```json
{"text": "今天天气很好，我们去公园散步。", "lang": "zh"}
```

| Field | Type | Rules |
|---|---|---|
| `text` | string | required, 1–4000 chars, stripped |
| `lang` | `"en"` \| `"zh"` \| `"auto"` | default `"auto"`; server re-detects from the text (any CJK ⇒ `zh`) and ignores a mismatching hint |

**Response (verified 2026-11-07)**

```json
{
  "text": "今天天气很好，我们去公园散步。",
  "mode": "paragraph",
  "language": "zh",
  "segments": [
    {"surface": "今天", "kind": "compound", "word_en": "today", "word_zh": "今天",
     "pinyin": "jīn tiān", "part_of_speech": "noun",
     "meaning_en": "today", "meaning_zh": "今天", "meaning_ne": "आज",
     "source": "ai", "note": ""},
    {"surface": "很好", "kind": "phrase", "word_en": "very good", "meaning_ne": "धेरै राम्रो",
     "source": "ai"},
    {"surface": "，", "kind": "punctuation", "source": "unresolved"}
  ],
  "whole": {
    "en": "Today the weather is great, we go to the park for a walk.",
    "zh": "今天天气很好，我们去公园散步。",
    "ne": "आज मौसम राम्रो छ, हामी पार्कमा टहिल्न जाऔं।"
  },
  "degraded": false,
  "error": ""
}
```

Enumerations (exhaustive):

| `kind` | Meaning | UI bucket |
|---|---|---|
| `word` | single word | words |
| `compound` | multi-character/compound word (水果, 公园) | words |
| `phrase` | multi-word phrase (很好, keep an eye on) | idioms/phrases |
| `idiom` | figurative idiom/proverb | idioms/phrases |
| `punctuation` | kept for readability | hidden |
| `function` | grammatical glue (the, a, 的, 了) | hidden |
| `other` | numbers / unclassifiable | words |

| `source` | Meaning |
|---|---|
| `dataset` | from `en_zh_ne.json` |
| `phrase` | from the curated phrase DB (`app/text_analysis/phrases.py`) |
| `ai` | filled by the LLM |
| `stopword` | function word, intentionally blank |
| `unresolved` | still blank (also used for punctuation) |

| `degraded` | Meaning |
|---|---|
| `false` | every content unit has a meaning (or is punctuation/function) |
| `true` | at least one content unit is still `unresolved` — show the amber banner |

`error` is only set for empty/whitespace-only input (`"No translatable content
found"`), in which case `segments` is empty. `whole` is `null` when the AI is
unavailable. **HTTP is 200 in all of these cases.**

Guarantees clients may rely on:
- segment order equals reading order; punctuation is preserved between words;
- `surface` concatenation reconstructs the input (whitespace normalized by the
  segmenter for Latin runs);
- at most 60 distinct unresolved surfaces are sent to the AI per request;
- the first call in a process may take ~+390 ms (jieba dictionary load).

---

## 7. `POST /api/v1/search/sentence`

**Request** `{"sense_id": "light_noun_illumination", "word": "light"}`
(`word` required ≥1 char; `sense_id` optional but preferred)

**Response**

```json
{"sense_id": "…", "word": "light", "en": "…", "zh": "…", "ne": "…",
 "source": "reviewed", "review_status": "approved"}
```

Priority: dataset reviewed example → AI draft (quality-checked) → template.
`source` ∈ `reviewed` \| `ai` \| `fallback`; `review_status` ∈ `approved` \|
`unreviewed`. The AI path can return `approved` when the cheap shape + Devanagari
checks pass — that is a **prioritisation signal, not proof** (see `MODEL-CONTRACTS.md`).

---

## 8. `GET /api/v1/popular` and `GET /api/v1/suggest`

```
GET /api/v1/popular?limit=6          → {"words": ["light","trade", …]}
GET /api/v1/suggest?q=li&lang=en     → {"suggestions": ["light"]}
```

`limit` defaults to 6 (no maximum enforced). `q` is required, 1–80 chars,
`lang` ∈ `en|zh`. Suggest does a prefix match over `word_en` (or `word_zh`) and
returns at most 6. Both are **unpaginated and unsorted beyond dataset order**.

---

## 9. Authenticated endpoints

Header: `Authorization: Bearer <supabase access token>` (HS256, `sub` = user id).

| Endpoint | Success body | Failure |
|---|---|---|
| `GET /me` | `{"uid": "...", "email": "..."}` | 503 no secret / 401 bad token |
| `GET /favorites` | `{"entry_ids": ["light", …]}` | 503 / 401 / 500 DB |
| `POST /favorites` `{"entry_id": "…"}` | full list (idempotent insert) | 503 / 401 / 500 |
| `DELETE /favorites/{entry_id}` | full list | 503 / 401 / 500 |
| `POST /feedback` `{"sense_id","field","comment"}` | `{"id": 1, "status": "flagged"}` | 503 / 401 / 500 |

`field` ≤ 40 chars (default `meaning`), `comment` ≤ 2000 chars, `sense_id` ≤ … no
max but required. Favorites are per `user_id`, unique per `(user_id, entry_id)`
enforced in code (exists-check), not by a DB constraint in the model.

**Important:** the app does **not** call these; it writes to the Supabase table
`favorites` directly. Two implementations of the same feature exist — do not
assume they share state semantics.

---

## 10. Client-side (internal) contracts

### 10.1 `ApiClient` (`lib/data/api_client.dart`)

| Method | Contract |
|---|---|
| `Future<DictionaryEntry?> search(String query, InputLanguage lang)` | POST `/search`; returns `null` on any failure, null entry, or bad shape |
| `Future<bool> isReachable()` | GET `/health`; any exception ⇒ `false` |
| `Future<AnalyzedText?> analyzeText(String text, InputLanguage lang)` | POST `/analyze/text`; `null` on any failure |

All requests carry a Supabase JWT automatically **when** Supabase is configured
and a session exists (interceptor). Dio timeouts: 25 s connect + receive.

### 10.2 `DictionaryRepository` (`lib/data/dictionary_repository.dart`)

| Method | Contract |
|---|---|
| `Future<List<DictionaryEntry>> load()` | lazy, idempotent; throws `DatasetLoadFailure` |
| `Future<DictionaryEntry?> search(String q, InputLanguage lang)` | exact → prefix → pinyin (Chinese only) |
| `Future<DictionaryEntry?> findById(String entryId)` | linear scan |
| `Future<List<DictionaryEntry>> popular(int limit)` | **first N entries of the asset**, not a popularity score |

### 10.3 Riverpod contracts

| Provider | Type | Contract |
|---|---|---|
| `resultProvider(SearchArgs)` | `FutureProvider.family<DictionaryEntry?, SearchArgs>` | `SearchArgs` **must** implement `==`/`hashCode` |
| `analyzeProvider(AnalyzeArgs)` | `FutureProvider.family<AnalyzedText?, AnalyzeArgs>` | same rule |
| `favoritesProvider` | `AsyncNotifier<List<String>>` | local wins; remote merge best-effort |
| `settingsProvider` | `Notifier<AppSettings>` | **in-memory**, resets on restart |
| `historyProvider` | `Notifier<List<String>>` | max 20, dedup, newest first |
| `backendReachableProvider` | `FutureProvider<bool>` | one-shot, not polled |

### 10.4 Model mapping rules

- `Sense.meaningNeStatus` ∈ `ai_draft` \| `machine_checked` \| `human_reviewed` \|
  `published` \| `flagged`; the app only *displays* `published`/AI content
  identically — it does not gate on status today.
- `ExampleSentence.isPublished` means `review_status == 'approved'`;
  `Sense.reviewedExample` prefers the first approved example, otherwise the first.
- `AnalyzedSegment.hasMeaning` = any of `meaning_en|zh|ne` non-empty. UI buckets:
  `AnalyzedText.idioms` = kind `idiom|phrase`; `AnalyzedText.words` = everything
  except punctuation/idiom/phrase/function.

---

## 11. Contract change procedure

1. Propose the additive field (name, type, nullability, semantics).
2. Update the pydantic schema **and** the Dart model with a safe default.
3. Update this document + the example payload.
4. Add a test asserting the new field (backend) and a decode test (Dart).
5. Ship backend first (old clients ignore unknown keys), then the app.

---

## 12. Image endpoints (added for the image pipeline)

### `GET /api/v1/images`

| Param | Type | Rules |
|---|---|---|
| `entry_id` | string | `zh23847`, `23847` or a fixture id; required |
| `limit` | int | 1–5, default 3 |

`200` always — a word with no picture is not an error:

```json
{
  "entry_id": "zh4360",
  "items": [{
    "image_id": 2,
    "thumb_url": "http://…/static/images/8b/8b6c…_256.jpg",
    "detail_url": "http://…/static/images/8b/8b6c…_800.jpg",
    "width": 1600, "height": 1200,
    "attribution": "Modern_bra_fullcup.jpg — Steifer with help of Gytha — CC BY-SA 3.0 via Wikimedia Commons",
    "license": "CC BY-SA 3.0",
    "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
    "source_url": "https://commons.wikimedia.org/wiki/File:…",
    "confidence": 0.85,
    "match_method": "wikipedia-lead-image"
  }],
  "icon": "everyday"
}
```

- `items: []` + `icon` is the "no image" contract. `icon` is an entry category
  key (`nature`, `transport`, `everyday`, `idiom`, `proper_noun`, `general`, …);
  the client maps it to a Material icon.
- Only `status = 'approved'` images are returned; rejected/removed rows stay in
  the database for audit but never reach the client.
- `attribution` is stored per image and must be rendered verbatim — CC BY and
  CC BY-SA require author + licence + source.
- Files are served by `/static/images/**` from `backend/data/images`; the mount
  only exists when the pipeline has produced files, so a fresh checkout still boots.
- `image_base_url` (settings) overrides the host used to build URLs when the
  backend sits behind a proxy or a CDN.

### `GET /api/v1/images/batch`

`entry_ids` = comma-separated, **max 50**, `limit` per entry 1–5 (default 2).
Returns a list of the same objects in the requested order, for search-result
thumbnails. Same no-image contract per entry.

Redis caching and CDN cache headers are specified but **not implemented**; each
call currently runs one indexed SQLite read.
