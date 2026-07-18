"""Strict BE-010 system health, metrics, and log query contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.admin import PageMetadata
from app.providers import ProviderType


class StrictObservabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComponentStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"


class SystemHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"


class ComponentHealthView(StrictObservabilityModel):
    component: str = Field(min_length=1, max_length=32)
    status: ComponentStatus
    latency_ms: int = Field(ge=0)
    detail: str = Field(min_length=1, max_length=64)


class AdminSystemHealthView(StrictObservabilityModel):
    status: SystemHealthStatus
    checked_at: datetime
    components: list[ComponentHealthView]


class ProviderMetricItem(StrictObservabilityModel):
    provider_type: ProviderType
    vendor: str
    model: str
    calls: int = Field(ge=0)
    errors: int = Field(ge=0)
    rate_limited: int = Field(ge=0)
    average_latency_ms: float = Field(ge=0)
    p95_latency_ms: int = Field(ge=0)
    error_rate: float = Field(ge=0, le=1)


class ProviderMetricsView(StrictObservabilityModel):
    since: datetime
    until: datetime
    items: list[ProviderMetricItem]


class OperationalLogSource(StrEnum):
    REQUEST = "REQUEST"
    AGENT = "AGENT"
    AUDIT = "AUDIT"
    ERROR = "ERROR"


class AdminLogItem(StrictObservabilityModel):
    id: str = Field(min_length=1, max_length=128)
    source: OperationalLogSource
    level: str = Field(min_length=1, max_length=16)
    message: str = Field(min_length=1, max_length=255)
    trace_id: str = Field(min_length=1, max_length=128)
    context: dict[str, Any]
    created_at: datetime


class AdminLogPage(StrictObservabilityModel):
    items: list[AdminLogItem]
    page: PageMetadata
    truncated: bool
