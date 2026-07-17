"""Application settings sourced from environment.

No real secrets are committed. The JWT secret and admin password are read from
the environment at runtime (see BE-002 identity). Provider/DB credentials land
behind explicit config objects; the renderer never receives any of these.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings for the FastAPI service."""

    # Service identity
    service_name: str = _env("PYMENTOR_SERVICE_NAME", "api")
    version: str = _env("PYMENTOR_SERVICE_VERSION", "0.0.0")
    log_level: str = _env("PYMENTOR_LOG_LEVEL", "INFO")

    # Database (set by docker-compose / tests via PYMENTOR_DATABASE_URL)
    database_url: str = _env(
        "PYMENTOR_DATABASE_URL",
        "postgresql+psycopg://pymentor:pymentor_dev@localhost:5432/pymentor",
    )

    # JWT — the secret MUST be provided in any non-test environment.
    # Dev default is long enough to satisfy HS256's 32-byte recommendation.
    jwt_secret: str = _env(
        "PYMENTOR_JWT_SECRET",
        "dev-only-insecure-secret-change-me-in-production-min-32-bytes",
    )
    jwt_algorithm: str = _env("PYMENTOR_JWT_ALGORITHM", "HS256")
    access_token_ttl_minutes: int = int(_env("PYMENTOR_ACCESS_TOKEN_TTL_MINUTES", "15"))
    refresh_token_ttl_days: int = int(_env("PYMENTOR_REFRESH_TOKEN_TTL_DAYS", "7"))

    # Initial System Admin bootstrap (frozen design §17.3.1).
    initial_admin_email: str = _env("PYMENTOR_INITIAL_ADMIN_EMAIL", "")
    initial_admin_password: str = _env("PYMENTOR_INITIAL_ADMIN_PASSWORD", "")

    # Default tenant for student self-registration.
    default_tenant_id: str = _env("PYMENTOR_DEFAULT_TENANT_ID", "tnt_default")
    demo_tenant_id: str = _env("PYMENTOR_DEMO_TENANT_ID", "tnt_demo")


def get_settings() -> Settings:
    """Return the current settings (re-reads env; cheap enough for bootstrap)."""

    return Settings()
