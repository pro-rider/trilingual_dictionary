from fastapi import APIRouter

from app.ai import provider as ai

router = APIRouter(tags=["providers"])

_SCHEMA = "providers.v2"


@router.get("/providers")
def providers():
    """Current router statistics, contract v2.

    The v1 payload (``chain`` / ``max_retries`` / per-provider metrics) described
    the legacy ``FailoverLLMService``. After the strict free-only router swap
    this view kept reading those keys while ``FreeOnlyRouter.stats()`` never
    emitted them, so the endpoint raised ``KeyError`` and returned HTTP 500.

    Two fields are derived here, and their meaning is stated rather than
    implied:

    * ``active`` — endpoint keys that pass the free policy *and* carry a
      credential (``provider.active_endpoint_keys()``). It is an eligibility
      list, not a health claim: an endpoint can be eligible and still fail.
    * ``all_down`` — True when that list is empty.
    """
    stats = ai.provider_stats()
    active = ai.active_endpoint_keys()
    return {
        "schema": _SCHEMA,
        "ai_enabled": ai.ai_enabled(),
        "active": active,
        "all_down": not active,
        **stats,
    }


@router.get("/providers/health")
def providers_health():
    """Free-verification, breaker and quota snapshot.

    Every value comes from in-process state, so this call makes no provider
    request and consumes no quota. Model IDs, prices and breaker/pool state only;
    no credential ever appears in this payload.
    """
    return {"schema": "providers.health.v1", "ai_enabled": ai.ai_enabled(), **ai.ai_health()}
