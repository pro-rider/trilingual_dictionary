# MODEL-CONTRACTS.md — NLP / Translation / AI Contracts

> **Read this first:** this project has **no trained or locally deployed ML models**.
> There is no translation model, no embedding index, no language-identification
> model, no tokenizer model, no ONNX/TFLite asset. Everything that looks like
> "AI" is either a **rule-based/lexical pipeline** or a **remote LLM HTTP call**
> routed through one failover service.

Anyone documenting or extending this system must describe the rule-based path
honestly. Do not write "the model translates", do not invent confidence scores,
BLEU numbers, or an "on-device NLP engine".

---

## 1. Component inventory (what actually exists)

| Component | Kind | Where | Deterministic? |
|---|---|---|---|
| Sentence/word segmenter | rule-based + jieba dictionary | `app/text_analysis/segmenter.py` | yes |
| Curated phrase/idiom DB | hand-written lexical data (**21** zh words, **33** idioms/proverbs) | `app/text_analysis/phrases.py` | yes |
| Stopword lists | hand-written (~50 EN, ~12 CJK) | `app/text_analysis/analyzer.py` | yes |
| Dataset lookup | exact/prefix index over JSON | `app/services/dataset.py` | yes |
| Nepali romanisation | fixed character map | `app/utils/romanize_ne.py` | yes |
| Text generation (meanings, examples, whole-sentence translation) | **remote LLM** (Groq / Gemini / OpenRouter) | `app/ai/*` | no (temperature 0.4) |
| Failover / circuit breaker | rule-based controller | `app/ai/failover.py` | yes (decisions) |
| Quality gate | shape + script check, **no scoring** | `app/services/quality.py` | yes |

`jieba` is a **dictionary-based** segmenter — it is not a neural tokenizer. It is
optional: if the import fails, `_greedy_cjk()` takes over.

---

## 2. Input/output contract

| | |
|---|---|
| Input languages | English, Chinese (Simplified). `lang ∈ en\|zh\|auto` |
| Output languages | English, 中文, नेपाली (Devanagari) |
| Nepali input | **not supported** as a search or analysis query |
| Encoding | UTF‑8; Chinese stored as Simplified; Nepali in Devanagari (never romanised in payloads) |
| Max analysis input | 4000 characters |
| Max search input | 80 characters |
| Max unresolved surfaces sent to the LLM | **60** per request (`_MAX_AI_SURFACES`) |
| AI output format | one JSON object, strict keys (see §4) |

---

## 3. Segmentation contract

### 3.1 Latin / English

- Split on whitespace; trailing punctuation split off the token and preserved as
  `kind="punctuation"`.
- Case is preserved for display, lower-cased for matching against the phrase DB
  and dataset (this fixes the "The" vs "the" mismatch).
- No stemming, no lemmatisation, no spell correction.

### 3.2 Chinese

```
jieba.cut(text, HMM=False)          # dictionary mode, no HMM new-word guessing
  → _split_low_freq(): if a token's frequency < 100 and it can be split into two
    tokens each ≥ 100, split it (recovers 今天 / 公园 from over-long merges)
  → _merge_known(): re-join adjacent tokens when the curated word list or the
    dataset knows the longer surface (策划词条优先)
  → fallback: _greedy_cjk() longest-match over the curated list + dataset when
    jieba is unavailable
```

Observed behaviour (2026‑11‑07): `今天天气很好，我们去公园散步。` →
`今天 / 天气 / 很 / 好 / ，/ 我们 / 去 / 公园 / 散步 / 。` — `很+好` is merged by the
AI-span step into `很好` only when the model proposes it (§4.3).

### 3.3 Classification

Order inside `_build_segments`:

1. **Idiom/proverb match first** (multi-word surfaces) — this is why
   `a piece of cake` does not lose its leading `a`.
2. Dataset exact match.
3. Curated phrase DB.
4. Stopword lists → `kind="function"`, `source="stopword"` (blank meanings).
5. Otherwise `unresolved`.

`degraded` is computed **only over content units** — a sentence consisting of
`the` or `的` must not raise the banner.

---

## 4. Remote LLM contract

### 4.1 Providers and endpoints

| Provider | Protocol | Endpoint | Auth |
|---|---|---|---|
| Groq | OpenAI-compatible chat completions | `POST {GROQ_BASE_URL}/chat/completions` | `Authorization: Bearer <key>` |
| OpenRouter | OpenAI-compatible chat completions | `POST {OPENROUTER_BASE_URL}/chat/completions` | `Authorization: Bearer <key>` + `HTTP-Referer`/`X-Title` |
| Gemini | native REST `generateContent` | `POST {GEMINI_BASE_URL}/models/{model}:generateContent` | `?key=<key>` in the **URL** |

Default chain: `groq → gemini → openrouter`.

Model IDs default to `openai/gpt-oss-120b` (Groq), `gemini-2.0-flash` (Gemini),
`meta-llama/llama-3.1-70b-instruct` (OpenRouter). All are configurable
(`ENV-CONTRACTS.md` §2.3) and none is guaranteed to be enabled on the account —
the effective model can be read from `/api/v1/providers`.

### 4.2 Request parameters (fixed contract)

| Parameter | Value | Rationale |
|---|---|---|
| `temperature` | **0.4** | stable, slightly varied phrasing |
| `response_format` | `{"type": "json_object"}` (OpenAI-compatible) | machine-parseable |
| Gemini `responseMimeType` | `application/json` | same intent |
| Gemini `temperature` | 0.4 | parity |
| System/user split | one system message (role + rules) + one user message (payload) | single round trip |
| Timeouts | 40 s per provider (configurable) | above p95 observed latency (~4 s) |

### 4.3 Batching and span merging

- One request covers **all unresolved units** (≤ 60). There is no per-word call.
- The prompt asks for `{"words": {"<surface>": {...}}, "whole": {...}}`.
- `_extract_json()` tolerates markdown fences and leading prose before the first
  `{`.
- Match is case-insensitive and whitespace-normalised (`_norm`).
- **Span acceptance:** if the model returns a surface that is the concatenation of
  adjacent unresolved units (`很`+`好` → `很好`), the segmenter accepts the merged
  span and marks the remaining parts resolved (`_merge_ai_spans`). This is the
  only place where the model may change segmentation.

### 4.4 Required JSON shape (analysis)

```json
{
  "words": {
    "<surface>": {
      "kind": "word|compound|phrase|idiom|function",
      "word_en": "...", "word_zh": "...", "pinyin": "...",
      "part_of_speech": "noun|verb|adj|adv|...",
      "meaning_en": "...", "meaning_zh": "...", "meaning_ne": "Devanagari ..."
    }
  },
  "whole": {"en": "...", "zh": "...", "ne": "Devanagari ..."}
}
```

Missing keys ⇒ the unit stays `unresolved`; nothing throws. Values are coerced to
strings; `meaning_ne` is kept as given (no script enforcement here).

### 4.5 Failover semantics (exact)

| Event | Behaviour |
|---|---|
| Provider returns 200 + parsable text | success, chain stops |
| 429 / rate-limit | **no retry on that provider**, jump to next immediately |
| Transport error / 5xx / empty body | retry up to `AI_MAX_RETRIES` (default 1) with `AI_RETRY_BACKOFF_SECONDS` (0.5 s) |
| Consecutive failures ≥ `CIRCUIT_FAIL_THRESHOLD` (3) | circuit opens for `CIRCUIT_COOLDOWN_SECONDS` (30 s); provider is skipped without a call |
| All providers fail | `complete()` returns `(None, "none", stats)`; callers degrade gracefully |
| Provider disabled or keyless | excluded from the chain entirely |

Metrics per provider (`success_count`, `failure_count`, `consecutive_failures`,
`avg_latency_ms`, `last_latency_ms`, `last_error`) are process-local and reset on
restart. A retry that eventually succeeds does **not** increment `failure_count`
(tested in `tests/test_failover.py`).

---

## 5. Quality gate (what is *not* checked)

`app/services/quality.py` only guarantees shape:

- all three of `en`, `zh`, `ne` non-empty;
- `ne` contains at least one Devanagari codepoint;
- `validate_shape` / `validate_language_fields` return human-readable issues.

`alignment_score()` is a **hardcoded 0.5 placeholder**. There is no semantic
alignment, no back-translation, no embedding similarity. Do not present 0.5 as a
confidence value anywhere in UI, docs, or API text.

Consequence: an AI example can pass the gate while being semantically wrong.
Acknowledgement of that risk is the reason every AI artifact carries a status
marker (§6) and the reason curated data wins.

---

## 6. Provenance and trust model

| Artifact produced by AI | Marker |
|---|---|
| Search sense | `meaning_ne_status = "ai_generated"` (from the AI draft path) |
| Example sentence | `source = "ai"`, `review_status = "ai_generated"` |
| Analysis segment | `source = "ai"` |
| Whole translation | present in `whole`, no marker field |

Rule: **AI output is never authoritative.** Review state transitions are
`ai_draft → machine_checked → human_reviewed → published`; only human review may
set `published`. The app does not currently display these statuses.

---

## 7. Observed behaviour (evidence, not promises)

Measured on the dev machine, 2026‑11‑07, backend on `127.0.0.1:8000`, AI enabled
via the legacy Groq key:

| Case | Result |
|---|---|
| `POST /search {"q":"light","lang":"en"}` | dataset hit, no AI call, 3–73 ms |
| `POST /analyze/text` Chinese full sentence | `degraded=false`, correct Nepali for 今天/天气/公园, **≈4220 ms** |
| `POST /analyze/text` English `The weather is nice today` | `the/is` → `function`, no banner |
| `the early bird catches the worm` | matched as one idiom, no leading-article loss |
| AI disabled, unknown word | `entry: null`, HTTP 200 |
| AI disabled, Chinese sentence | `degraded=true`, unresolved blanks kept |

These numbers are a point-in-time observation of a third-party API, not a
contract. Re-measure before quoting them in a report.

---

## 8. Failure matrix (what users see)

| Condition | Search | Analysis | Sentence |
|---|---|---|---|
| dataset hit | entry | segments filled | reviewed example |
| miss + AI up | `ai_generated` entry | AI-filled, `degraded=false` | AI example |
| miss + AI down | "not found" | amber banner, partial | template sentence |
| Supabase off | unaffected | unaffected | unaffected |
| Postgres off | unaffected | unaffected | unaffected |
| dataset file missing | 500 | 500 | 500 |

---

## 9. Rules for extending

Allowed without redesign:
- add curated idioms/words to `phrases.py` (helps both segmentation and trust);
- add a provider that speaks the OpenAI chat-completions shape (`app/ai/providers.py`);
- raise `_MAX_AI_SURFACES` after measuring payload size and latency;
- add a deterministic post-check (e.g. reject Latin characters inside `meaning_ne`).

Requires explicit approval (contract change):
- changing the JSON schema, temperature, or batching strategy;
- adding a **local** model of any kind (this document must then gain a real
  "model card": artefact path, licence, size, inputs/outputs, latency, memory);
- introducing embedding search, back-translation scoring, or a new quality metric
  (must define the metric, its scale, and its validation set — 0.5 placeholders
  are forbidden);
- changing failover ordering, retry counts, or circuit thresholds (update
  `tests/test_failover.py` in the same change).

Forbidden:
- documenting model capabilities that do not exist;
- exposing provider keys or raw prompts to the client;
- logging user text at INFO level (privacy, `SECURITY.md` §7).
