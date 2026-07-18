"""Encrypted, tenant-scoped Provider configuration persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import Enum as SqlEnum
from sqlalchemy.types import Uuid

from app.db import Base
from app.providers import ProviderType


class ProviderConfig(Base):
    __tablename__ = "provider_configs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider_type",
            "vendor",
            "model",
            name="uq_provider_configs_identity",
        ),
        Index(
            "uq_provider_configs_enabled_type",
            "tenant_id",
            "provider_type",
            unique=True,
            postgresql_where=text("enabled"),
        ),
        CheckConstraint("version >= 1", name="ck_provider_configs_version_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_type: Mapped[ProviderType] = mapped_column(
        SqlEnum(ProviderType, native_enum=False, length=32), nullable=False, index=True
    )
    vendor: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    api_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
