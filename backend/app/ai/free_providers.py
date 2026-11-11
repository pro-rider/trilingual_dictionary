"""HTTP callers that raise typed failures instead of returning ``None``.

Returning ``None`` on every problem (what the legacy providers do) destroys the
information the router needs to decide "retry", "cool down", "never call this
again". These callers preserve it, redact secrets, and never put a key in a URL
(so it cannot leak through proxy logs or exception strings).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.ai.errors import (AuthFailed, ConnectionFailed, InvalidModel,
                           ParseFailure, ProviderTimeout, RateLimited,
                           ServerError)
from app.ai.registry import ModelEndpoint
from app.ai.redaction import register_secret

_client: httpx.Client | None = None


def client() -> httpx.Client:
    """One pooled client for the process; creating one per request leaks sockets."""
    global _client
    if _client is None:
        _client = httpx.Client(
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            http2=False,
        )
    return _client


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _raise_for_status(resp: httpx.Response, label: str) -> None:
    code = resp.status_code
    if code < 400:
        return
    ra = _retry_after(resp)
    if code == 429:
        raise RateLimited(f"{label} HTTP 429", status_code=code, retry_after=ra)
    if code in (401, 403):
        raise AuthFailed(f"{label} HTTP {code}", status_code=code)
    if code in (400, 404, 410, 422):
        raise InvalidModel(f"{label} HTTP {code}", status_code=code)
    if code >= 500:
        raise ServerError(f"{label} HTTP {code}", status_code=code)
    raise InvalidModel(f"{label} HTTP {code}", status_code=code)


class OpenAICompatibleCaller:
    """Works for Groq and OpenRouter (same wire format)."""

    def __init__(self, endpoint: ModelEndpoint, *, force_json: bool = True) -> None:
        self.endpoint = endpoint
        register_secret(endpoint.api_key())

    def complete(self, prompt: str) -> str:
        ep = self.endpoint
        body: dict[str, Any] = {
            "model": ep.model_id,
            "temperature": 0.3,
            "messages": [{"role": "system", "content": prompt}],
        }
        if ep.supports_json:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {ep.api_key()}",
                   "Content-Type": "application/json", **ep.extra_headers}
        try:
            resp = client().post(f"{ep.base_url}/chat/completions", headers=headers,
                                 json=body, timeout=ep.timeout_seconds)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"{ep.key} timeout") from exc
        except httpx.HTTPError as exc:
            raise ConnectionFailed(f"{ep.key} {type(exc).__name__}") from exc
        _raise_for_status(resp, ep.key)
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ParseFailure(f"{ep.key} malformed chat payload") from exc
        if not isinstance(content, str) or not content.strip():
            raise ParseFailure(f"{ep.key} empty completion")
        return content


class GeminiCaller:
    """Google's native generateContent. Key goes in a header, never the query."""

    def __init__(self, endpoint: ModelEndpoint) -> None:
        self.endpoint = endpoint
        register_secret(endpoint.api_key())

    def complete(self, prompt: str) -> str:
        ep = self.endpoint
        url = f"{ep.base_url}/models/{ep.model_id}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": ep.api_key()}
        body: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3,
                                 **({"responseMimeType": "application/json"}
                                    if ep.supports_json else {})},
        }
        try:
            resp = client().post(url, headers=headers, json=body,
                                 timeout=ep.timeout_seconds)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"{ep.key} timeout") from exc
        except httpx.HTTPError as exc:
            raise ConnectionFailed(f"{ep.key} {type(exc).__name__}") from exc
        _raise_for_status(resp, ep.key)
        try:
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ParseFailure(f"{ep.key} malformed generateContent payload") from exc
        if not isinstance(text, str) or not text.strip():
            raise ParseFailure(f"{ep.key} empty completion")
        return text


def build_caller(endpoint: ModelEndpoint):
    if endpoint.endpoint_type == "gemini":
        return GeminiCaller(endpoint)
    return OpenAICompatibleCaller(endpoint)


def valid_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (ValueError, TypeError):
        return False
