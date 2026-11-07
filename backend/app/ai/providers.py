"""Concrete LLM providers.

- :class:`OpenAICompatibleProvider` — works for any OpenAI-compatible
  ``/chat/completions`` endpoint (Groq, OpenRouter, Together, ...).
- :class:`GeminiProvider` — Google's native ``generateContent`` API.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.ai.base import LLMProvider, ProviderRateLimit


class OpenAICompatibleProvider(LLMProvider):
    """Generic OpenAI-compatible chat-completions provider."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        enabled: bool,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            name=name, api_key=api_key, model=model, timeout=timeout, enabled=enabled
        )
        self.base_url = base_url.rstrip("/")
        self.extra_headers = extra_headers or {}

    def complete(self, system_prompt: str) -> str | None:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        payload = {
            "model": self.model,
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system_prompt}],
        }
        try:
            resp = httpx.post(
                url, headers=headers, json=payload, timeout=self.timeout
            )
            if resp.status_code == 429:
                raise ProviderRateLimit(f"{self.name} HTTP 429 (rate limit)")
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return data["choices"][0]["message"]["content"]
        except ProviderRateLimit:
            raise
        except Exception:
            return None


class GeminiProvider(LLMProvider):
    """Google Gemini via the native generateContent API."""

    def __init__(
        self,
        *,
        name: str = "gemini",
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        enabled: bool,
    ) -> None:
        super().__init__(
            name=name, api_key=api_key, model=model, timeout=timeout, enabled=enabled
        )
        self.base_url = base_url.rstrip("/")

    def complete(self, system_prompt: str) -> str | None:
        url = (
            f"{self.base_url}/models/{self.model}:generateContent"
            f"?key={self.api_key}"
        )
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": system_prompt}]}],
            "generationConfig": {
                "temperature": 0.4,
                "responseMimeType": "application/json",
            },
        }
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=self.timeout)
            if resp.status_code == 429:
                raise ProviderRateLimit(f"{self.name} HTTP 429 (rate limit)")
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except ProviderRateLimit:
            raise
        except Exception:
            return None
