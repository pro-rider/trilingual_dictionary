"""Abstract provider interface for the multi-provider LLM failover system."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderError(Exception):
    """Base for provider-level failures."""


class ProviderRateLimit(ProviderError):
    """Raised when the provider returns HTTP 429 (rate limit / out of quota).

    The failover service treats this specially: it is likely to persist for a
    short window, so we skip to the next provider immediately without wasting
    retries.
    """


class LLMProvider(ABC):
    """A single LLM backend (Groq / Gemini / OpenRouter ...).

    Implementations are stateless except for immutable config; per-call state
    (circuit breaker, metrics) lives in the failover service.
    """

    name: str = "base"

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        model: str,
        timeout: float,
        enabled: bool,
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.enabled = enabled

    @property
    def active(self) -> bool:
        """A provider participates only when enabled and has a key."""
        return self.enabled and bool(self.api_key)

    @abstractmethod
    def complete(self, system_prompt: str) -> str | None:
        """Ask the model for a reply and return the raw text.

        Returns ``None`` on any failure (the concrete implementation should
        raise :class:`ProviderRateLimit` on HTTP 429 so the caller can route
        around it immediately).
        """
