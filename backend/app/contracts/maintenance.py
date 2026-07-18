"""Strict wire contracts for privileged database and privacy maintenance."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictMaintenanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MaintenanceConfirmationRequest(StrictMaintenanceModel):
    confirmation: str = Field(min_length=1, max_length=128)


class DatabaseRestoreRequest(MaintenanceConfirmationRequest):
    backup_id: UUID


class DatabaseTableUsage(StrictMaintenanceModel):
    name: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=0)
    estimated_rows: int = Field(ge=0)


class DatabaseBackupView(StrictMaintenanceModel):
    id: UUID
    status: str = Field(min_length=1, max_length=16)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    created_at: datetime


class DatabaseStatusView(StrictMaintenanceModel):
    connected: bool
    engine: str = Field(pattern=r"^PostgreSQL$")
    schema_revision: str = Field(min_length=1, max_length=32)
    database_size_bytes: int = Field(ge=0)
    active_connections: int = Field(ge=0)
    slow_query_count: int = Field(ge=0)
    table_count: int = Field(ge=0)
    tables: list[DatabaseTableUsage]
    last_backup: DatabaseBackupView | None


class MaintenanceOperationView(StrictMaintenanceModel):
    id: UUID
    operation: str = Field(min_length=1, max_length=32)
    status: str = Field(min_length=1, max_length=16)
    backup_id: UUID | None
    error_code: str | None = Field(max_length=64)
    requested_at: datetime
    completed_at: datetime | None


class StudentDeleteView(StrictMaintenanceModel):
    student_id: UUID
    deleted: bool


class DemoResetView(StrictMaintenanceModel):
    tenant_id: UUID
    reset: str = Field(pattern=r"^completed$")
    users_removed: int = Field(ge=0)
