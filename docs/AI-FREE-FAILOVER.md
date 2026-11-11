# Strict zero-cost AI failover (20 slots)

Status: implemented, tested, and exercised against live providers on 2026-11-11.
Scope: `backend/app/ai/` and `backend/app/core/config.py`. No Flutter change, no
key in the client, no paid endpoint reachable by configuration.

## 1. What this guarantees

| Guarantee | How it is enforced | Test |
|---|---|---|
| No paid endpoint is ever called | Registry marks priced slots `free_verified=False` + `disabled_reason`; `free_policy.decide()` refuses them | `test_paid_endpoint_is_never_selected` |
| Unknown pricing = not free | `input_price`/`output_price == None` denies the slot | `test_unknown_price_is_treated_as_paid` |
| A missing key = disabled, not "try anyway" | `ModelEndpoint.configured` | `test_missing_credential_disables_endpoint` |
| Bounded work per request | `max_attempts`, `max_retries_per_provider`, `max_total_request_seconds`, per-attempt hard deadline | `test_attempt_budget_is_bounded` |
| One account quota is one pool | `account_quota_pool` on every slot; 429 cools the pool, not the model | `test_rate_limit_cools_the_whole_pool`, `test_quota_daily_cap_blocks_pool` |
| Permanent failures are not retried | `auth` / `invalid_model` open the breaker after one call | `test_auth_failure_opens_breaker_immediately`, `test_invalid_model_is_not_retried` |
| Malformed output never becomes data | `response_format` + `_is_json` validation; failures stay out of `ai_candidates` | `test_invalid_json_is_rejected` |
| Exhaustion is reported, not faked | `complete()` returns `(None, "none", stats)` with per-attempt reasons | `test_all_exhausted_returns_controlled_failure` |
| No credential in logs/stats | `redaction.register_secret()` + pattern scrub | `test_secret_is_redacted_in_stats` |

## 2. Registry: 20 slots, 14 usable, 6 blocked (honest shortfall)

Verified free (`GET https://openrouter.ai/api/v1/models`, condition
`pricing.prompt == "0" and pricing.completion == "0"`, 469 models → 15 zero-priced):

| Slot | Provider | Model | Note |
|---|---|---|---|
| 1 | Groq | `openai/gpt-oss-120b` | free tier, RPM/RPD limited |
| 2 | Gemini | `gemini-3.8-flash` | free tier; present in the account's model list |
| 3 | OpenRouter | `meta-llama/llama-3.1-70b-instruct` | **disabled**: priced |
| 4 | OpenRouter | `nvidia/nemotron-3-ultra-550b-a55b:free` | |
| 5 | OpenRouter | `nvidia/nemotron-3.5-super-vl:free` | vision |
| 6 | OpenRouter | `nvidia/nemotron-3.5-lightning:free` | |
| 7 | OpenRouter | `liquid/lfm-2.5-2.6b:free` | |
| 8 | OpenRouter | `liquid/lfm-3-1.7b:free` | |
| 9 | OpenRouter | `google/gemma-4-26b-a4b-it:free` | |
| 10 | OpenRouter | `google/gemma-4-31b-it:free` | |
| 11 | OpenRouter | `cohere/north-mini-code:free` | code-tuned, JSON unverified |
| 12 | OpenRouter | `dots-studio/dots-3-note-preview:free` | |
| 13 | OpenRouter | `recursive/flint-v1.0:free` | |
| 14 | OpenRouter | `thinkingmachines/inkling-2-small:free` | |
| 15 | OpenRouter | `openrouter/free` | aggregator; routed model not named |
| 16 | Z.AI | `glm-4.5-flash` | **blocked**: free eligibility unverifiable without a plan |
| 17–19 | Cloudflare | Qwen / Llama / Gemma | **blocked**: daily Neuron allowance bills past the cap |
| 20 | Mistral | `mistral-small-latest` | **blocked**: experiment tier can convert to paid |

Shortfall statement: **20 slots configured, 14 zero-priced (registry-verified),
13 active, and only 10 confirmed by an actual API call on 2026-11-11.** Six slots
are disabled for cost-policy reasons. The user's list asked for Qwen / DeepSeek /
Mistral / Llama free variants on OpenRouter; none of them appear in the current
zero-price catalogue, so those three slots are not manufactured.

Live probe of every active endpoint (one tiny JSON request each, 15 s cap):

| Slot | Endpoint | Result |
|---|---|---|
| 1 | groq:openai/gpt-oss-120b | HTTP 403 — key rejected |
| 2 | gemini:gemini-3.8-flash | **ok, but 171 s** (last resort only) |
| 4 | nvidia/nemotron-3-ultra-550b-a55b:free | ok, 3.3 s |
| 5 | nvidia/nemotron-3.5-super-vl:free | ok, 1.3 s |
| 6 | nvidia/nemotron-3.5-lightning:free | ok, 3.6 s |
| 7 | liquid/lfm-2.5-2.6b:free | ok, 1.2 s |
| 8 | liquid/lfm-3-1.7b:free | ok, 1.2 s |
| 9 | google/gemma-4-26b-a4b-it:free | HTTP 429 |
| 10 | google/gemma-4-31b-it:free | HTTP 429 |
| 11 | cohere/north-mini-code:free | ok, 2.1 s |
| 12 | dots-studio/dots-3-note-preview:free | ok, 2.6 s (leading whitespace) |
| 13 | recursive/flint-v1.0:free | ok, 1.7 s |
| 14 | thinkingmachines/inkling-2-small:free | HTTP 403 — no access → now disabled |
| 15 | openrouter/free | ok, 5.0 s |

Result: 10 of 14 answered; 4 did not (1 bad credential, 1 no model access, 2
rate-limited). "Verified free" therefore means *price verified*, not *usable*.

Quota pools: **3** (`groq-free-tier`, `gemini-free-tier`, `openrouter-free-models`).
Twelve OpenRouter free models share one key → one pool. Reporting them as twelve
independent quotas would be false.

## 3. Request path

```
API route → ai_guard (kill switch, X-AI-Token, rate limits)
        → provider.generate_draft
        → FreeOnlyRouter.complete
             free_policy → capability filter → endpoint breaker → pool quota
             → caller (httpx, pooled, key in header) → JSON validation
             → success ? return : record failure, cool down, next endpoint
```

Modules: `registry.py`, `free_policy.py`, `router.py`, `breaker.py`, `quota.py`,
`errors.py`, `redaction.py`, `free_providers.py`, `discovery.py`.

## 4. Failure classification and retry

| Kind | Source | Retried? | Cools down |
|---|---|---|---|
| `rate_limit` | 429 | no | pool (Retry-After honoured) |
| `auth` | 401/403 | no | endpoint, breaker opens immediately |
| `invalid_model` | 400/404/410/422 | no | endpoint |
| `timeout` | socket / hard deadline | no (fail over) | endpoint |
| `connection` | DNS, reset, TLS | yes (bounded) | endpoint |
| `server` | 5xx | yes (bounded) | endpoint + pool |
| `parse` | bad JSON, empty content | yes (bounded) | no |
| `free_policy` | policy denial | no | endpoint |
| `unexpected` | anything else | **no** | none |

Backoff: exponential, capped at 8 s, plus 0–0.4 s jitter; `Retry-After` capped
at 5 s so one provider cannot stall the request.

## 5. Security

* Keys are looked up at call time (env → settings), never stored on the endpoint
  dataclass, so `repr()`, logs and stats cannot carry them.
* Gemini now sends `x-goog-api-key` as a header; the legacy provider put the key
  in the URL query string, which leaks into proxy and error logs.
* `redaction.py` scrubs registered secrets plus `Authorization`, `key=`, `sk-…`,
  `AIza…` patterns from every message that reaches stats.
* Health output (`provider.ai_health()`) contains model IDs, prices, breaker
  states and pool counters — no credentials.

## 6. Live verification (FACT)

Command: one real request through `_service.complete` with the configured keys.

```
groq   → HTTP 403 (auth)          → breaker open, no retry
gemini → timeout ×3 @41 s         → 123 s wasted (fixed: timeouts no longer retry)
openrouter:nvidia/nemotron-3-ultra-550b-a55b:free → ok, returned {"ok": true}
```

After the timeout-policy fix the same run costs one 41 s attempt, then fails
over. Also verified: `GET /v1beta/models` (Gemini) returns 200 and lists
`gemini-3.8-flash`; `GET /openai/v1/models` (Groq) returns **403** for the
configured key, so slot 1 is unusable until that credential is replaced.

Root cause note (FACT): the per-attempt cap is enforced by a thread deadline
wrapper, not by httpx's `timeout` argument. A direct caller call with
`timeout=40` returned after **171 s**, which is why the wrapper exists.

## 6b. Registry count history (why an earlier run showed "0 active")

The first probe ran before credentials were injected: every endpoint read
`os.environ[api_key_env]`, while the Groq key actually lives in the legacy
`AI_API_KEY` field, so `configured` was false for all slots and the summary
printed `active: 0`. `set_credentials()` now injects validated settings, and the
same probe prints `slots: 20 / active: 13`. The contradiction was a real bug, not
a reporting artefact.

## 7. Local fallback

`ai_enable_local_fallback` exists but no caller is wired: Ollama is optional,
never a dependency, and nothing is downloaded automatically. Adding a
`OllamaCaller` is the only remaining step and is deliberately out of scope here
(no local model installed on this machine to verify against).

## 8. Tests

```
pytest tests/test_ai_free_failover.py -q   → 19 passed
pytest tests/test_failover.py tests/test_ai_fallback.py tests/test_ai_hardening.py -q → 28 passed
```

## 9. Known limitations / remaining work

1. Groq credential returns 403 → slot 1 disabled in practice (breaker in memory
   only; a restart clears it, so the first request after a restart re-learns it).
2. Gemini `generateContent` hangs past 40 s for this account; the hard deadline
   caps the damage but the endpoint is effectively unusable until investigated.
3. Breaker and quota state are in memory + a temp-dir JSON file; not shared
   across processes/workers.
4. `openrouter/free` is an aggregator: the routed model is not reported back,
   so provenance for its answers is weaker than for a named model.
5. Cloudflare / Z.AI / Mistral verification requires an account and a billing
   boundary we refuse to cross; they stay disabled by design.
6. Relevance/quality validation is JSON-shape only; semantic checking remains
   the job of the existing candidate + human review workflow.
