"""Least-privilege system health, Provider metrics, and redacted log APIs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.contracts.observability import (
    AdminLogPage,
    AdminSystemHealthView,
    ComponentHealthView,
    ComponentStatus,
    OperationalLogSource,
    ProviderMetricsView,
    SystemHealthStatus,
)
from app.db import get_db
from app.models import User
from app.observability import aggregate_provider_metrics, list_admin_logs
from app.providers import ProviderType
from app.rbac import require_course_admin, require_system_admin

router = APIRouter(prefix="/api/v1/admin/system", tags=["admin-observability"])


@dataclass(frozen=True, slots=True)
class ComponentProbe:
    component: str
    status: str
    latency_ms: int
    detail: str


SystemHealthProbe = Callable[[Session], list[ComponentProbe]]


def _timed(component: str, operation: Callable[[], bool]) -> ComponentProbe:
    started = perf_counter()
    try:
        ready = operation()
    except Exception:
        ready = False
    return ComponentProbe(
        component=component,
        status="HEALTHY" if ready else "DEGRADED",
        latency_ms=max(0, int((perf_counter() - started) * 1000)),
        detail="ready" if ready else "unavailable",
    )


def probe_system_health(db: Session) -> list[ComponentProbe]:
    settings = get_settings()

    def _postgres() -> bool:
        return bool(db.scalar(text("SELECT 1")) == 1)

    def _redis() -> bool:
        client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        try:
            return bool(client.ping())
        finally:
            client.close()

    def _http(url: str) -> bool:
        response = httpx.get(url, timeout=2.0, follow_redirects=False)
        return response.status_code < 400

    object_scheme = "https" if settings.object_store_secure else "http"
    return [
        ComponentProbe("api", "HEALTHY", 0, "ready"),
        _timed("worker", lambda: _http(settings.worker_health_url)),
        _timed("sandbox", lambda: _http(f"{settings.sandbox_supervisor_url.rstrip('/')}/healthz")),
        _timed("redis", _redis),
        _timed("postgresql", _postgres),
        _timed(
            "object_store",
            lambda: _http(f"{object_scheme}://{settings.object_store_endpoint}/minio/health/live"),
        ),
    ]


def get_system_health_probe() -> SystemHealthProbe:
    return probe_system_health


def _window(since: datetime | None, until: datetime | None) -> tuple[datetime, datetime]:
    end = until or datetime.now(UTC)
    start = since or end - timedelta(hours=24)
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="timezone-aware metrics window required",
        )
    if start >= end or end - start > timedelta(days=31):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="metrics window must be positive and no longer than 31 days",
        )
    return start, end


@router.get("/health", response_model=AdminSystemHealthView)
async def admin_system_health(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_course_admin),
    probe: SystemHealthProbe = Depends(get_system_health_probe),
) -> AdminSystemHealthView:
    components = probe(db)
    views = [
        ComponentHealthView(
            component=item.component,
            status=ComponentStatus(item.status),
            latency_ms=item.latency_ms,
            detail=item.detail,
        )
        for item in components
    ]
    overall = (
        SystemHealthStatus.HEALTHY
        if all(item.status == ComponentStatus.HEALTHY for item in views)
        else SystemHealthStatus.DEGRADED
    )
    return AdminSystemHealthView(
        status=overall,
        checked_at=datetime.now(UTC),
        components=views,
    )


@router.get("/metrics", response_model=ProviderMetricsView)
async def admin_provider_metrics(
    since: datetime | None = None,
    until: datetime | None = None,
    provider_type: ProviderType | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> ProviderMetricsView:
    start, end = _window(since, until)
    return aggregate_provider_metrics(
        db,
        tenant_id=admin.tenant_id,
        since=start,
        until=end,
        provider_type=provider_type,
    )


@router.get("/logs", response_model=AdminLogPage)
async def admin_system_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    source: OperationalLogSource | None = None,
    level: str | None = Query(default=None, min_length=1, max_length=16),
    trace_id: str | None = Query(default=None, min_length=1, max_length=128),
    since: datetime | None = None,
    until: datetime | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> AdminLogPage:
    if since is not None and until is not None and since > until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid log time window",
        )
    return list_admin_logs(
        db,
        tenant_id=admin.tenant_id,
        page=page,
        page_size=page_size,
        source=source,
        level=level,
        trace_id=trace_id,
        since=since,
        until=until,
    )
