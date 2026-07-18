"""Redacted persistence and tenant-scoped aggregation for BE-010 operations."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.admin_queries import redact_admin_snapshot
from app.contracts.admin import PageMetadata
from app.contracts.observability import (
    AdminLogItem,
    AdminLogPage,
    OperationalLogSource,
    ProviderMetricItem,
    ProviderMetricsView,
)
from app.logging import redact_value
from app.models import AgentRun, AuditEvent, OperationalLog, ProviderCallRecord
from app.providers import ProviderType

_LOG_SCAN_LIMIT = 5_000
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def record_operational_log(
    db: Session,
    *,
    tenant_id: UUID | None,
    source: str,
    level: str,
    message: str,
    trace_id: str,
    context: dict[str, Any],
    created_at: datetime | None = None,
) -> OperationalLog:
    source_value = OperationalLogSource(source).value
    level_value = level.upper()
    if level_value not in _LOG_LEVELS:
        raise ValueError("invalid operational log level")
    safe_context = redact_value(context)
    if not isinstance(safe_context, dict):
        safe_context = {}
    row = OperationalLog(
        tenant_id=tenant_id,
        source=source_value,
        level=level_value,
        message=message[:255] or "operation recorded",
        trace_id=trace_id[:128],
        context_data=safe_context,
    )
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    db.flush()
    return row


def record_provider_call(
    db: Session,
    *,
    tenant_id: UUID,
    provider_type: ProviderType,
    vendor: str,
    model: str,
    operation: str,
    outcome: str,
    latency_ms: int,
    rate_limited: bool,
    trace_id: str,
    provider_config_id: UUID | None = None,
    input_units: int = 0,
    output_units: int = 0,
    status_code: int | None = None,
    error_code: str | None = None,
    created_at: datetime | None = None,
) -> ProviderCallRecord:
    if outcome not in {"SUCCEEDED", "FAILED"}:
        raise ValueError("invalid Provider call outcome")
    if min(latency_ms, input_units, output_units) < 0:
        raise ValueError("Provider metric values cannot be negative")
    row = ProviderCallRecord(
        tenant_id=tenant_id,
        provider_config_id=provider_config_id,
        provider_type=provider_type,
        vendor=vendor[:64],
        model=model[:128],
        operation=operation[:64],
        outcome=outcome,
        latency_ms=latency_ms,
        input_units=input_units,
        output_units=output_units,
        rate_limited=rate_limited,
        status_code=status_code,
        error_code=None if error_code is None else error_code[:64],
        trace_id=trace_id[:128],
    )
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    db.flush()
    return row


def aggregate_provider_metrics(
    db: Session,
    *,
    tenant_id: UUID,
    since: datetime,
    until: datetime,
    provider_type: ProviderType | None,
) -> ProviderMetricsView:
    predicates = [
        ProviderCallRecord.tenant_id == tenant_id,
        ProviderCallRecord.created_at >= since,
        ProviderCallRecord.created_at <= until,
    ]
    if provider_type is not None:
        predicates.append(ProviderCallRecord.provider_type == provider_type)
    rows = list(db.scalars(select(ProviderCallRecord).where(*predicates)))
    groups: dict[tuple[ProviderType, str, str], list[ProviderCallRecord]] = defaultdict(list)
    for row in rows:
        groups[(row.provider_type, row.vendor, row.model)].append(row)
    items: list[ProviderMetricItem] = []
    for (kind, vendor, model), calls in sorted(
        groups.items(), key=lambda item: tuple(str(part) for part in item[0])
    ):
        latencies = sorted(call.latency_ms for call in calls)
        errors = sum(call.outcome != "SUCCEEDED" for call in calls)
        rate_limited = sum(call.rate_limited for call in calls)
        p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
        items.append(
            ProviderMetricItem(
                provider_type=kind,
                vendor=vendor,
                model=model,
                calls=len(calls),
                errors=errors,
                rate_limited=rate_limited,
                average_latency_ms=sum(latencies) / len(latencies),
                p95_latency_ms=latencies[p95_index],
                error_rate=errors / len(calls),
            )
        )
    return ProviderMetricsView(since=since, until=until, items=items)


def list_admin_logs(
    db: Session,
    *,
    tenant_id: UUID,
    page: int,
    page_size: int,
    source: OperationalLogSource | None,
    level: str | None,
    trace_id: str | None,
    since: datetime | None,
    until: datetime | None,
) -> AdminLogPage:
    include_operational = source in (None, OperationalLogSource.REQUEST, OperationalLogSource.ERROR)
    include_audit = source in (None, OperationalLogSource.AUDIT)
    include_agent = source in (None, OperationalLogSource.AGENT)
    items: list[AdminLogItem] = []

    if include_operational:
        operational_rows = list(
            db.scalars(
                select(OperationalLog)
                .where(
                    or_(
                        OperationalLog.tenant_id == tenant_id,
                        OperationalLog.tenant_id.is_(None),
                    )
                )
                .order_by(OperationalLog.created_at.desc(), OperationalLog.id.desc())
                .limit(_LOG_SCAN_LIMIT)
            )
        )
        for row in operational_rows:
            row_source = OperationalLogSource(row.source)
            if source is not None and row_source != source:
                continue
            items.append(
                AdminLogItem(
                    id=str(row.id),
                    source=row_source,
                    level=row.level,
                    message=row.message,
                    trace_id=row.trace_id,
                    context=redact_admin_snapshot(row.context_data),
                    created_at=row.created_at,
                )
            )

    if include_audit:
        audit_rows = list(
            db.scalars(
                select(AuditEvent)
                .where(AuditEvent.tenant_id == tenant_id)
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                .limit(_LOG_SCAN_LIMIT)
            )
        )
        items.extend(
            AdminLogItem(
                id=str(row.id),
                source=OperationalLogSource.AUDIT,
                level="INFO",
                message=row.action[:255],
                trace_id=row.trace_id,
                context=redact_admin_snapshot(
                    {
                        "resource_type": row.resource_type,
                        "resource_id": row.resource_id,
                        "detail": row.detail,
                    }
                ),
                created_at=row.created_at,
            )
            for row in audit_rows
        )

    if include_agent:
        agent_rows = list(
            db.scalars(
                select(AgentRun)
                .where(AgentRun.tenant_id == tenant_id)
                .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                .limit(_LOG_SCAN_LIMIT)
            )
        )
        items.extend(
            AdminLogItem(
                id=str(row.id),
                source=OperationalLogSource.AGENT,
                level="ERROR" if row.error_code or row.status == "FAILED" else "INFO",
                message=f"agent run {row.status.lower()}",
                trace_id=row.trace_id,
                context={
                    "external_run_id": row.external_run_id,
                    "route": row.route,
                    "status": row.status,
                    "latest_sequence": row.latest_sequence,
                    "fallback_used": row.fallback_used,
                    "error_code": row.error_code,
                },
                created_at=row.created_at,
            )
            for row in agent_rows
        )

    if level is not None:
        items = [item for item in items if item.level == level.upper()]
    if trace_id is not None:
        items = [item for item in items if item.trace_id == trace_id]
    if since is not None:
        items = [item for item in items if item.created_at >= since]
    if until is not None:
        items = [item for item in items if item.created_at <= until]
    items.sort(key=lambda item: (item.created_at, item.id), reverse=True)
    truncated = len(items) >= _LOG_SCAN_LIMIT
    total = len(items)
    start = (page - 1) * page_size
    return AdminLogPage(
        items=items[start : start + page_size],
        page=PageMetadata(
            number=page,
            size=page_size,
            total_items=total,
            total_pages=math.ceil(total / page_size) if total else 0,
        ),
        truncated=truncated,
    )
