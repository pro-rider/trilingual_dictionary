# AI providers — configuration and current state

The backend never hardcodes a key. Every provider is configured through
environment variables, and the registry (`backend/app/ai/registry.py`) builds the
endpoint list from them at import time.

## Free / default lane

Variables already in use:

| variable | used for |
|---|---|
| `AI_API_KEY` | Groq |
| `GEMINI_API_KEY` | Google Gemini |
| `OPENROUTER_API_KEY` | OpenRouter free models |
| `AI_SHARED_SECRET` | optional shared token; when set, `X-AI-Token` must match |
| `AI_ALLOW_PAID` | `1`/`true` enables the paid lane |
| `PAID_PROVIDER_BASE_URL` | paid lane base URL (OpenAI-compatible) |
| `PAID_PROVIDER_MODEL` | paid lane model id |
| `PAID_PROVIDER_API_KEY_ENV` | **name** of the variable holding the key (default `PAID_PROVIDER_API_KEY`) |

The paid lane is slot 21 and is disabled unless `AI_ALLOW_PAID` is set **and**
both a base URL and a model are present. It is never used as a fallback for the
free lane (`free_verified=False`), so a misconfigured paid lane cannot silently
start spending.

## Current state (measured 2026-11-12, `python backend/tools/provider_health.py`)

| provider | status | evidence |
|---|---|---|
| Groq | **unusable** | HTTP 403, `error code: 1010` — region block |
| OpenRouter (free) | **out of quota** | HTTP 402 "can only afford 617", then SSL `UNEXPECTED_EOF_WHILE_READING` |
| Gemini | **unusable** | 503s and connection timeouts on the configured models |
| paid lane | **not configured** | no base URL / model / key |

Consequence: the "AI fills a missing entry" path is effectively absent in
production today. That is recorded as the top item in `docs/BLOCKED.md`.

## Adding a paid provider (operator steps)

1. Choose a vendor that offers an OpenAI-compatible `/chat/completions`.
2. Export the four variables above in the deployment environment —
   **never** in a committed file.
3. Run `python backend/tools/provider_health.py`; it prints per-provider verdicts
   and must show `working` before any generator is re-run.
4. Check `GET /api/v1/providers/health` on the running server: it reads live
   breaker and quota state, so a green CLI but a red endpoint means the server
   process has a different environment.

## Safety rules that do not change with a paid key

- `X-AI-Token` is a speed bump, not a security control: it ships inside the APK
  and can be extracted. Real protection is the per-device/per-IP rate limit plus
  the global budget.
- The kill-switch file `ai_enabled` (see `ai_guard`) stops AI without a restart.
- Total failure returns a clean "not found yet" payload with diagnostics; it
  never fabricates a definition.
- No user text is logged. `backend/app/core/obs.py` enforces this with a field
  allow-list, and `backend/tests/test_obs.py` asserts it.
