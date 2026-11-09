"""Provider abstraction.

A provider produces text only.  It can never set candidate state, approve,
import, or mark human verification — that is enforced downstream in the ledger.
"""

from __future__ import annotations

from typing import Protocol

from ..domain.models import GenerationRequest, ProviderResult, SenseRef


class ProviderError(RuntimeError):
    code = "provider_error"


class ProviderTimeout(ProviderError):
    code = "provider_timeout"


class ProviderInvalidJSON(ProviderError):
    code = "provider_invalid_json"


class ProviderFailure(ProviderError):
    code = "provider_failure"


class Provider(Protocol):
    name: str
    model: str

    def parameters(self) -> dict:
        """Resolved generation settings (temperature, top_p, ...).

        These are identity, not comments: they are stored in provenance and
        hashed into request fingerprint v2.  A provider that has no tunable
        settings returns ``{}`` — never ``None``.
        """
        ...

    def generate(self, request: GenerationRequest, sense: SenseRef) -> ProviderResult: ...
