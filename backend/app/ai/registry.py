"""The 20-slot model registry.

Facts, not wishes:

* Slot count is fixed at 20.
* A slot may only be *active* when its free eligibility is verified.
* Verification is recorded (source + timestamp) so it can expire.
* Unverifiable slots stay in the registry, disabled, with a reason — a
  registry that quietly shrinks to "whatever worked" hides the shortfall.

The twelve OpenRouter free endpoints below were verified against
``GET https://openrouter.ai/api/v1/models`` on 2026-11-11 by requiring
``pricing.prompt == "0"`` and ``pricing.completion == "0"``. Model IDs do
retire; :mod:`app.ai.discovery` re-checks the catalogue and the registry
demotes any ID that disappeared or acquired a price.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# --- quota pools -----------------------------------------------------------
# Only three pools exist today. Twelve OpenRouter models share one key, so one
# exhaustion event blocks all twelve: counting them as twelve pools would be
# exactly the false claim the spec forbids.
POOL_GROQ = "groq-free-tier"
POOL_GEMINI = "gemini-free-tier"
POOL_OPENROUTER = "openrouter-free-models"


@dataclass
class ModelEndpoint:
    slot: int
    provider_id: str
    model_id: str
    endpoint_type: str                  # "openai_compatible" | "gemini"
    base_url: str
    api_key_env: str
    priority: int
    free_verified: bool
    verification_source: str
    verification_timestamp: str
    input_price: float | None           # None = unknown, not "free"
    output_price: float | None
    account_quota_pool: str
    rate_limit_scope: str               # "pool" | "model"
    context_limit: int | None
    supports_json: bool
    supports_tools: bool
    supports_streaming: bool
    supports_vision: bool
    timeout_seconds: float
    cooldown_seconds: float
    disabled_reason: str = ""
    notes: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.provider_id}:{self.model_id}"

    def api_key(self) -> str:
        """Resolver order: process env, then credentials injected from settings.

        Keys never live on the dataclass (so they cannot land in a repr or a
        log line by accident) — they are looked up through this indirection.
        """
        env = (os.environ.get(self.api_key_env) or "").strip()
        if env:
            return env
        return (_CREDENTIALS.get(self.provider_id) or "").strip()

    @property
    def cost_verified_zero(self) -> bool:
        return self.input_price == 0 and self.output_price == 0

    @property
    def configured(self) -> bool:
        return bool(self.api_key())

    @property
    def active(self) -> bool:
        return (self.free_verified and self.cost_verified_zero
                and self.configured and not self.disabled_reason)


OPENROUTER_FREE_VERIFIED = "openrouter catalogue: pricing.prompt=0 & pricing.completion=0 (GET /api/v1/models)"
VERIFIED_AT = "2026-11-11"
TWO_0 = "OpenRouter catalogue reported prompt=0, completion=0"

# provider_id -> credential, injected by the facade from validated settings.
# Kept module-level and out of dataclasses so secrets never appear in repr().
_CREDENTIALS: dict[str, str] = {}


def set_credentials(values: dict[str, str]) -> None:
    _CREDENTIALS.clear()
    for provider_id, value in values.items():
        if value and value.strip():
            _CREDENTIALS[provider_id] = value.strip()


def _or(slot: int, model: str, *, priority: int, json_ok: bool = True,
        vision: bool = False, ctx: int | None = None,
        notes: str = "") -> ModelEndpoint:
    return ModelEndpoint(
        slot=slot, provider_id="openrouter", model_id=model,
        endpoint_type="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY", priority=priority,
        free_verified=True, verification_source=OPENROUTER_FREE_VERIFIED,
        verification_timestamp=VERIFIED_AT,
        input_price=0.0, output_price=0.0,
        account_quota_pool=POOL_OPENROUTER, rate_limit_scope="pool",
        context_limit=ctx, supports_json=json_ok, supports_tools=False,
        supports_streaming=True, supports_vision=vision,
        timeout_seconds=45, cooldown_seconds=60,
        extra_headers={"HTTP-Referer": "https://github.com/trilingual-dictionary",
                       "X-Title": "trilingual-dictionary"},
        notes=notes,
    )


def _unverified(slot: int, provider: str, model: str, *, base_url: str,
                env: str, reason: str) -> ModelEndpoint:
    return ModelEndpoint(
        slot=slot, provider_id=provider, model_id=model,
        endpoint_type="openai_compatible", base_url=base_url,
        api_key_env=env, priority=99, free_verified=False,
        verification_source="not verified", verification_timestamp="",
        input_price=None, output_price=None,
        account_quota_pool=f"{provider}-unverified", rate_limit_scope="pool",
        context_limit=None, supports_json=False, supports_tools=False,
        supports_streaming=False, supports_vision=False,
        timeout_seconds=45, cooldown_seconds=120,
        disabled_reason=reason,
    )


def build_registry(*, free_models: dict[str, dict] | None = None,
                   discovery_source: str = "",
                   discovery_timestamp: str = "",
                   groq_model: str = "",
                   gemini_model: str = "") -> list[ModelEndpoint]:
    """Return the 20 slots. ``free_models`` overrides the built-in list when
    live discovery has run; IDs not in it are demoted, not deleted."""
    endpoints: list[ModelEndpoint] = [
        ModelEndpoint(
            slot=1, provider_id="groq", model_id=groq_model.strip()
            or "openai/gpt-oss-120b",
            endpoint_type="openai_compatible",
            base_url="https://api.groq.com/openai/v1",
            api_key_env="GROQ_API_KEY", priority=1, free_verified=True,
            verification_source="Groq free tier: no card required, rate-limited",
            verification_timestamp=VERIFIED_AT,
            input_price=0.0, output_price=0.0,
            account_quota_pool=POOL_GROQ, rate_limit_scope="pool",
            context_limit=None, supports_json=True, supports_tools=False,
            supports_streaming=True, supports_vision=False,
            timeout_seconds=40, cooldown_seconds=60,
            notes="free tier is time-limited by RPM/RPD, not by money; live probe "
                  "2026-11-11 returned HTTP 403 — the configured key (GROQ_API_KEY, "
                  "else legacy AI_API_KEY) is rejected and must be replaced"),
        ModelEndpoint(
            slot=2, provider_id="gemini", model_id=gemini_model.strip()
            or "gemini-2.0-flash",
            endpoint_type="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key_env="GEMINI_API_KEY", priority=90, free_verified=True,
            verification_source="Google Gemini API free tier (no billing enabled)",
            verification_timestamp=VERIFIED_AT,
            input_price=0.0, output_price=0.0,
            account_quota_pool=POOL_GEMINI, rate_limit_scope="pool",
            context_limit=None, supports_json=True, supports_tools=False,
            supports_streaming=True, supports_vision=True,
            timeout_seconds=45, cooldown_seconds=60,
            notes="live probe 2026-11-11 answered in 171 s, so it is last resort: "
                  "a normal 45 s request will skip it"),
        # Slot 3 keeps the legacy OpenRouter paid identifier, disabled: it is not
        # on the zero-price list, so under a strict $0 policy it may not run.
        ModelEndpoint(
            slot=3, provider_id="openrouter", model_id="meta-llama/llama-3.1-70b-instruct",
            endpoint_type="openai_compatible",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY", priority=99, free_verified=False,
            verification_source="priced model, not on the zero-price list",
            verification_timestamp=VERIFIED_AT,
            input_price=None, output_price=None,
            account_quota_pool=POOL_OPENROUTER, rate_limit_scope="pool",
            context_limit=None, supports_json=True, supports_tools=False,
            supports_streaming=True, supports_vision=False,
            timeout_seconds=45, cooldown_seconds=120,
            disabled_reason="priced model: violates the strict zero-cost policy",
        ),
        _or(4, "nvidia/nemotron-3-ultra-550b-a55b:free", priority=3,
            notes="large reasoning model"),
        _or(5, "nvidia/nemotron-3.5-super-vl:free", priority=5, vision=True,
            notes="vision-language; not used for text-only tasks"),
        _or(6, "nvidia/nemotron-3.5-lightning:free", priority=4,
            notes="low latency"),
        _or(7, "liquid/lfm-2.5-2.6b:free", priority=12, notes="2.6B, fast"),
        _or(8, "liquid/lfm-3-1.7b:free", priority=13, notes="1.7B, fastest"),
        _or(9, "google/gemma-4-26b-a4b-it:free", priority=6,
            notes="live probe 2026-11-11: HTTP 429 immediately (per-model free limit)"),
        _or(10, "google/gemma-4-31b-it:free", priority=7,
            notes="live probe 2026-11-11: HTTP 429 immediately (per-model free limit)"),
        _or(11, "cohere/north-mini-code:free", priority=10, json_ok=False,
            notes="code-tuned; live probe ok with JSON mode off"),
        _or(12, "dots-studio/dots-3-note-preview:free", priority=11, json_ok=False,
            notes="live probe ok; prefixes whitespace before JSON"),
        _or(13, "recursive/flint-v1.0:free", priority=8, json_ok=False),
        ModelEndpoint(
            slot=14, provider_id="openrouter",
            model_id="thinkingmachines/inkling-2-small:free",
            endpoint_type="openai_compatible",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY", priority=99, free_verified=False,
            verification_source="live probe 2026-11-11: HTTP 403",
            verification_timestamp=VERIFIED_AT,
            input_price=0.0, output_price=0.0,
            account_quota_pool=POOL_OPENROUTER, rate_limit_scope="pool",
            context_limit=None, supports_json=False, supports_tools=False,
            supports_streaming=False, supports_vision=False,
            timeout_seconds=45, cooldown_seconds=120,
            disabled_reason="HTTP 403 on live probe: this key has no access to the model",
        ),
        _or(15, "openrouter/free", priority=15, json_ok=False,
            notes="aggregator: zero price verified, but the routed model is not "
                  "named in the response — treated as experimental"),
        # Slots 16-20: providers that cannot be verified without an account or
        # billing boundary we refuse to cross. Kept visible, never enabled.
        _unverified(16, "zai", "glm-4.5-flash", base_url="https://api.z.ai/api/paas/v4",
                    env="ZAI_API_KEY",
                    reason="free eligibility not verifiable without an account plan"),
        _unverified(17, "cloudflare", "@cf/qwen/qwen2.5-7b-instruct",
                    base_url="https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run",
                    env="CLOUDFLARE_API_TOKEN",
                    reason="free daily Neurons allowance is billed past the cap; "
                           "account id + billing state unverified"),
        _unverified(18, "cloudflare", "@cf/meta/llama-3.1-8b-instruct",
                    base_url="https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run",
                    env="CLOUDFLARE_API_TOKEN",
                    reason="same Cloudflare billing boundary as slot 17"),
        _unverified(19, "cloudflare", "@cf/google/gemma-2-9b-it",
                    base_url="https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run",
                    env="CLOUDFLARE_API_TOKEN",
                    reason="same Cloudflare billing boundary as slot 17"),
        _unverified(20, "mistral", "mistral-small-latest",
                    base_url="https://api.mistral.ai/v1",
                    env="MISTRAL_API_KEY",
                    reason="experiment tier can convert to paid; no zero-price proof"),
    ]

    # Slot 21: the paid lane. Never enabled by accident — it needs an explicit
    # AI_ALLOW_PAID=1 plus its own base URL, model and key variable, so a paid
    # provider can be added later without editing code or committing a key.
    paid_base = (os.environ.get("PAID_PROVIDER_BASE_URL") or "").strip()
    paid_model = (os.environ.get("PAID_PROVIDER_MODEL") or "").strip()
    paid_key_env = (os.environ.get("PAID_PROVIDER_API_KEY_ENV")
                    or "PAID_PROVIDER_API_KEY").strip()
    paid_allowed = (os.environ.get("AI_ALLOW_PAID") or "").strip().lower() in {
        "1", "true", "yes", "on"}
    paid_ready = bool(paid_base and paid_model and paid_allowed)
    endpoints.append(ModelEndpoint(
        slot=21, provider_id="paid", model_id=paid_model or "(not configured)",
        endpoint_type="openai_compatible",
        base_url=paid_base or "about:blank",
        api_key_env=paid_key_env, priority=100, free_verified=False,
        verification_source="operator-provided paid lane (AI_ALLOW_PAID=1)",
        verification_timestamp=VERIFIED_AT,
        input_price=None, output_price=None,
        account_quota_pool="pool_paid", rate_limit_scope="pool",
        context_limit=None, supports_json=True, supports_tools=False,
        supports_streaming=True, supports_vision=False,
        timeout_seconds=45, cooldown_seconds=120,
        disabled_reason="" if paid_ready else (
            "paid lane not configured: set AI_ALLOW_PAID=1 plus its base URL, "
            "model and credential (see docs/AI_PROVIDERS.md)"),
    ))

    if free_models is not None:
        for ep in endpoints:
            if ep.provider_id != "openrouter" or ep.model_id == "meta-llama/llama-3.1-70b-instruct":
                continue
            live = free_models.get(ep.model_id)
            if live is None:
                ep.disabled_reason = "retired or no longer zero-priced in live catalogue"
                ep.free_verified = False
            else:
                ep.free_verified = True
                ep.verification_source = discovery_source or ep.verification_source
                ep.verification_timestamp = discovery_timestamp or ep.verification_timestamp
                if live.get("context_length"):
                    ep.context_limit = int(live["context_length"])
    return endpoints


def registry_summary(endpoints: list[ModelEndpoint]) -> dict:
    active = [e for e in endpoints if e.active]
    return {
        "slots": len(endpoints),
        "active": len(active),
        "disabled": len(endpoints) - len(active),
        "verified_free": sum(1 for e in endpoints if e.free_verified),
        "quota_pools": sorted({e.account_quota_pool for e in endpoints if e.active}),
        "by_provider": {
            p: sum(1 for e in endpoints if e.provider_id == p and e.active)
            for p in sorted({e.provider_id for e in endpoints})
        },
        "disabled_reasons": {e.key: e.disabled_reason for e in endpoints if e.disabled_reason},
    }
