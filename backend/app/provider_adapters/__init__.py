"""Provider native-protocol adapters (BE-022 / BE-024 / BE-025).

This package wraps each non-conversational capability (TTS, ASR, OCR, …) behind
a small, vendor-agnostic Python interface. Each adapter:

- reads its credentials through the BE-019 encrypted ``provider_configs`` row
  (``kind`` matches ``ProviderType``), so secrets are never re-implemented;
- exposes a typed ``generate``-style method returning a dataclass result;
- supports a clearly-labelled **mock mode** (default when no live credential is
  authorized, or when the corresponding ``PYMENTOR_*_MOCK=1`` flag is set) so the
  full surface is exercised in CI without ever calling a live vendor endpoint.

Live verification is intentionally out of scope here (tracked as INT-010
NOT-RUN); the live code paths are wired but never invoked from tests.

Shared primitives live below so sibling adapters (BE-024 ASR, BE-025 OCR) can
reuse the same ``ProviderUnavailable`` error type and the same
``MockCapableAdapter`` resolution helper without duplicating logic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.providers import ProviderType, ResolvedProvider


class ProviderUnavailable(RuntimeError):
    """No enabled provider of the requested type is available for this tenant.

    Mapped by the API layer to ``ErrorCode.PROVIDER_UNAVAILABLE`` (HTTP 503).
    Raised instead of returning a degraded artifact so the teaching loop can
    branch on a typed error and the caller never silently receives mock bytes
    when it expected live output.
    """


class ProviderAdapterError(RuntimeError):
    """A live provider call failed for a transport/auth/protocol reason."""


def mock_mode_enabled(*, flag_name: str, provider: ResolvedProvider | None) -> bool:
    """Resolve whether an adapter should run in mock mode.

    Mock is engaged when EITHER:
    - the explicit ``PYMENTOR_*_MOCK=1`` env flag is set (operator override), OR
    - no enabled ``provider_configs`` row exists for this ``(tenant, type)``.

    When a real credential IS authorized the adapter runs live unless the
    operator explicitly forces mock. Tests never set up a live credential.
    """

    if os.environ.get(flag_name, "").lower() == "1":
        return True
    return provider is None


@dataclass(frozen=True, slots=True)
class _CapabilityMeta:
    """Static metadata describing an adapter capability (internal helper)."""

    provider_type: ProviderType
    vendor: str
    model: str


# Vendor adapters are re-exported here so the API layer imports from a single
# package root (e.g. ``from app.provider_adapters import build_asr_adapter``).
# Each sibling adapter (TTS BE-022, OCR BE-024, ASR BE-025) adds itself below
# as it lands.
from app.provider_adapters.asr_xunfei import (  # noqa: E402 - after shared types
    XunfeiAsrAdapter,
    build_asr_adapter,
)
from app.provider_adapters.ocr_xunfei import (  # noqa: E402 - after shared types
    OcrXunfeiAdapter,
    build_ocr_adapter,
)

__all__ = [
    "OcrXunfeiAdapter",
    "ProviderAdapterError",
    "ProviderUnavailable",
    "XunfeiAsrAdapter",
    "build_asr_adapter",
    "build_ocr_adapter",
    "mock_mode_enabled",
]
