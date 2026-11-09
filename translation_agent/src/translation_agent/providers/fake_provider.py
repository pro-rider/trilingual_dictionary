"""Deterministic fake provider with fault injection.

Every test in this subsystem runs against this provider; no network, no
credentials, no cost.  The translation is derived from the sense key so two
runs of the same request produce byte-identical output.
"""

from __future__ import annotations

import json
import time

from ..domain.models import GenerationRequest, ProviderResult, SenseRef
from .base import ProviderFailure, ProviderInvalidJSON, ProviderTimeout


BEHAVIOURS = ("ok", "malformed", "invalid_json", "timeout", "failure", "latin", "echo")

_NEPALI_TOKENS = (
    "पानी", "किताब", "घर", "स्कूल", "बाटो", "खाना", "समय", "साथी",
    "हावा", "आकाश", "जमीन", "फूल", "रङ", "मन", "काम", "जीवन",
)


class FakeProvider:
    name = "fake"
    model = "fake-v1"

    def __init__(self, behaviours: dict[str, str] | None = None, default: str = "ok"):
        self._behaviours = dict(behaviours or {})
        self._default = default
        if self._default not in BEHAVIOURS:
            raise ValueError(f"unknown default behaviour {self._default!r}")

    def behaviour_for(self, sense_key: str) -> str:
        return self._behaviours.get(sense_key, self._default)

    def _text_for(self, sense: SenseRef) -> str:
        seed = sum(ord(c) for c in sense.sense_key)
        first, second = _NEPALI_TOKENS[seed % len(_NEPALI_TOKENS)], _NEPALI_TOKENS[
            (seed // 7) % len(_NEPALI_TOKENS)
        ]
        return f"{first} {second}"

    def parameters(self) -> dict:
        return {"temperature": 0.0, "deterministic": True, "max_tokens": 64}

    def generate(self, request: GenerationRequest, sense: SenseRef) -> ProviderResult:
        started = time.perf_counter()
        behaviour = self.behaviour_for(sense.sense_key)

        if behaviour == "timeout":
            raise ProviderTimeout(f"fake timeout for {sense.sense_key}")
        if behaviour == "failure":
            raise ProviderFailure(f"fake upstream failure for {sense.sense_key}")

        if behaviour == "malformed":
            raw = "not json at all"
        elif behaviour == "invalid_json":
            raw = json.dumps({"translation": 123, "confidence": 0.4})
        elif behaviour == "latin":
            raw = json.dumps({"translation": "water book", "confidence": 0.9})
        elif behaviour == "echo":
            raw = json.dumps({"translation": sense.gloss_en, "confidence": 0.9})
        else:
            raw = json.dumps(
                {
                    "translation": self._text_for(sense),
                    "confidence": 0.88,
                    "note": f"fake:{sense.entry_id}",
                },
                ensure_ascii=False,
            )

        latency = int((time.perf_counter() - started) * 1000)
        return ProviderResult(raw=raw, attempt=1, latency_ms=latency)


class RaisingProvider(FakeProvider):
    """Same as fake but raises after N successful calls — for atomicity tests."""

    def __init__(self, fail_after: int, **kwargs):
        super().__init__(**kwargs)
        self.fail_after = fail_after
        self.calls = 0

    def generate(self, request: GenerationRequest, sense: SenseRef) -> ProviderResult:
        self.calls += 1
        if self.calls > self.fail_after:
            raise ProviderFailure(f"injected failure after {self.fail_after} call(s)")
        return super().generate(request, sense)


def parse_translation(raw: str) -> dict:
    """Parse a provider payload into {translation, confidence}."""
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProviderInvalidJSON(f"provider returned non-JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProviderInvalidJSON("provider payload must be a JSON object")
    text = payload.get("translation")
    if not isinstance(text, str) or not text.strip():
        raise ProviderInvalidJSON("provider payload missing a non-empty 'translation'")
    confidence = payload.get("confidence")
    if confidence is not None and not isinstance(confidence, (int, float)):
        raise ProviderInvalidJSON("provider 'confidence' must be numeric or null")
    return {"translation": text, "confidence": confidence}
