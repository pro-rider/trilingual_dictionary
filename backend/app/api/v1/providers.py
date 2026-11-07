from fastapi import APIRouter

from app.ai import provider as ai

router = APIRouter(tags=["providers"])


@router.get("/providers")
def providers():
    """Per-provider health and metrics for the multi-provider LLM failover.

    Shows which providers are enabled/active, circuit-breaker state, call
    counts, average latency and last error — plus the configured chain order.
    """
    stats = ai.provider_stats()
    return {
        "ai_enabled": ai.ai_enabled(),
        "chain": stats["chain"],
        "active": stats["active"],
        "max_retries": stats["max_retries"],
        "providers": stats["providers"],
        "all_down": not stats["active"],
    }
