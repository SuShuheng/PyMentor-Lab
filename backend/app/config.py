"""Application settings sourced from environment.

No secrets are read here at the bootstrap stage. Provider/DB credentials land
in later tasks behind explicit, encrypted config objects (see BE-002/BE-003).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings for the FastAPI service skeleton."""

    service_name: str = _env("PYMENTOR_SERVICE_NAME", "api")
    version: str = _env("PYMENTOR_SERVICE_VERSION", "0.0.0")
    log_level: str = _env("PYMENTOR_LOG_LEVEL", "INFO")


def get_settings() -> Settings:
    """Return the current settings (re-reads env; cheap enough for bootstrap)."""

    return Settings()
