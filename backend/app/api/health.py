"""Health and connectivity endpoints.

- ``GET /health`` — liveness/readiness for probes and the admin health board.
- ``GET /system/ping`` — public connectivity test used by the renderer's
  server-address input (see frozen design §7.2). Returns no privileged detail.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.config import get_settings
from app.contracts.health import HealthResponse, HealthStatus, SystemPingResponse

router = APIRouter(tags=["system"])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status=HealthStatus.OK,
        service=settings.service_name,
        version=settings.version,
        timestamp=_now_iso(),
    )


@router.get("/system/ping", response_model=SystemPingResponse)
async def ping() -> SystemPingResponse:
    settings = get_settings()
    return SystemPingResponse(service=settings.service_name, timestamp=_now_iso())
