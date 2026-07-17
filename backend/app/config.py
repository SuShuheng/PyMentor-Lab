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

    # Agent audit stream consumer (BE-006). It is opt-in so unit tests and
    # one-off API processes never start a background Redis loop implicitly.
    redis_url: str = _env("PYMENTOR_REDIS_URL", "redis://127.0.0.1:6379/0")
    agent_event_consumer_enabled: bool = (
        _env("PYMENTOR_AGENT_EVENT_CONSUMER_ENABLED", "false").lower() == "true"
    )
    agent_event_stream: str = _env("PYMENTOR_AGENT_EVENT_STREAM", "pymentor:agent-events:v1")
    agent_event_group: str = _env("PYMENTOR_AGENT_EVENT_GROUP", "pymentor-api-v1")
    agent_event_consumer: str = _env("PYMENTOR_AGENT_EVENT_CONSUMER", "api-1")
    agent_event_block_ms: int = int(_env("PYMENTOR_AGENT_EVENT_BLOCK_MS", "1000"))
    agent_event_batch_size: int = int(_env("PYMENTOR_AGENT_EVENT_BATCH_SIZE", "25"))
    agent_event_claim_idle_ms: int = int(_env("PYMENTOR_AGENT_EVENT_CLAIM_IDLE_MS", "30000"))

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

    # Sandbox Supervisor (BE-005). The API signs execution requests to the
    # Supervisor using this shared secret; the Supervisor verifies them. The
    # runtime image and request timeout are also surfaced so the API can refuse
    # an unpinned image or an unreasonable timeout at startup.
    sandbox_secret: str = _env("PYMENTOR_SANDBOX_SECRET", "")
    sandbox_runtime_image: str = _env(
        "PYMENTOR_SANDBOX_RUNTIME_IMAGE",
        "pymentor/sandbox-runtime:1.0",
    )
    sandbox_supervisor_url: str = _env(
        "PYMENTOR_SANDBOX_SUPERVISOR_URL",
        "http://sandbox:8090",
    )
    sandbox_request_timeout_seconds: int = int(
        _env("PYMENTOR_SANDBOX_REQUEST_TIMEOUT_SECONDS", "30")
    )


def get_settings() -> Settings:
    """Return the current settings (re-reads env; cheap enough for bootstrap)."""

    return Settings()
