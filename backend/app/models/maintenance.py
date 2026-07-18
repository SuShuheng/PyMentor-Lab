"""Database backup and privileged maintenance operation records."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import Uuid

from app.db import Base


class DatabaseBackup(Base):
    """Opaque metadata for a versioned database archive in private object storage."""

    __tablename__ = "database_backups"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="ck_database_backups_size_nonnegative"),
        CheckConstraint("length(digest) = 64", name="ck_database_backups_digest_length"),
        CheckConstraint(
            "status IN ('AVAILABLE', 'INVALID')",
            name="ck_database_backups_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="AVAILABLE")
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class MaintenanceOperation(Base):
    """Auditable state for backup, restore, reset, and privacy deletion commands."""

    __tablename__ = "maintenance_operations"
    __table_args__ = (
        CheckConstraint(
            "operation_type IN ('DATABASE_BACKUP', 'DATABASE_RESTORE', "
            "'DEMO_TENANT_RESET', 'STUDENT_DELETE')",
            name="ck_maintenance_operations_type",
        ),
        CheckConstraint(
            "status IN ('SUCCEEDED', 'FAILED')",
            name="ck_maintenance_operations_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    backup_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("database_backups.id", ondelete="SET NULL"), nullable=True
    )
    requested_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
