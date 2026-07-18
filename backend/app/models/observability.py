"""Durable, redacted operations logs and Provider call metrics."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import Enum as SqlEnum
from sqlalchemy.types import Uuid

from app.db import Base
from app.providers import ProviderType


class OperationalLog(Base):
    __tablename__ = "operational_logs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    context_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class ProviderCallRecord(Base):
    __tablename__ = "provider_call_records"
    __table_args__ = (
        CheckConstraint("latency_ms >= 0", name="ck_provider_calls_latency_nonnegative"),
        CheckConstraint("input_units >= 0", name="ck_provider_calls_input_nonnegative"),
        CheckConstraint("output_units >= 0", name="ck_provider_calls_output_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    provider_config_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("provider_configs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_type: Mapped[ProviderType] = mapped_column(
        SqlEnum(ProviderType, native_enum=False, length=32), nullable=False, index=True
    )
    vendor: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    latency_ms: Mapped[int] = mapped_column(nullable=False)
    input_units: Mapped[int] = mapped_column(nullable=False, default=0)
    output_units: Mapped[int] = mapped_column(nullable=False, default=0)
    rate_limited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status_code: Mapped[int | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
