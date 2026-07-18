"""Health and connectivity endpoints.

- ``GET /health`` — liveness/readiness for probes and the admin health board.
- ``GET /system/ping`` — public connectivity test used by the renderer's
  server-address input (see frozen design §7.2). Returns no privileged detail.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status

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


@router.get("/ready", response_model=HealthResponse)
async def ready(request: Request, response: Response) -> HealthResponse:
    settings = get_settings()
    consumer_health = getattr(request.app.state, "agent_event_consumer_health", None)
    consumer_ready = not settings.agent_event_consumer_enabled or (
        consumer_health is not None and consumer_health.alive and consumer_health.ready
    )
    if not consumer_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status=HealthStatus.OK if consumer_ready else HealthStatus.DEGRADED,
        service=settings.service_name,
        version=settings.version,
        timestamp=_now_iso(),
    )


@router.get("/system/ping", response_model=SystemPingResponse)
async def ping() -> SystemPingResponse:
    settings = get_settings()
    return SystemPingResponse(service=settings.service_name, timestamp=_now_iso())
