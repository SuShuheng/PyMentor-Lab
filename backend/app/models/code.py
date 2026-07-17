"""Normalized persistence for sandbox code runs and learning evidence (BE-005)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import Uuid

from app.contracts.sandbox import (
    CodeRunMode,
    CodeRunStatus,
    SandboxComparison,
    TestVisibility,
)
from app.db import Base


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _enum(enum: type[StrEnum], *, length: int) -> SqlEnum:
    return SqlEnum(enum, native_enum=False, length=length)


class HintSource(StrEnum):
    STATIC = "STATIC"
    AGENT_PROPOSAL = "AGENT_PROPOSAL"


class CodeRevision(Base):
    __tablename__ = "code_revisions"
    __table_args__ = (
        UniqueConstraint("task_instance_id", "sequence", name="uq_code_revision_sequence"),
        UniqueConstraint("task_instance_id", "source_digest", name="uq_code_revision_digest"),
        CheckConstraint("sequence >= 1", name="ck_code_revision_sequence_positive"),
        CheckConstraint(
            "octet_length(source_code) BETWEEN 1 AND 65536",
            name="ck_code_revision_source_bytes",
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_instance_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("task_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    parent_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("code_revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class CodeRun(Base):
    __tablename__ = "code_runs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_code_runs_run_id"),
        UniqueConstraint("idempotency_key_id", name="uq_code_runs_idempotency_key"),
        CheckConstraint("version >= 1", name="ck_code_run_version_positive"),
        Index(
            "uq_code_run_active_task",
            "task_instance_id",
            unique=True,
            postgresql_where=text("status IN ('QUEUED', 'RUNNING')"),
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_instance_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("task_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("code_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    idempotency_key_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("idempotency_keys.id", ondelete="RESTRICT"),
        nullable=False,
    )
    mode: Mapped[CodeRunMode] = mapped_column(_enum(CodeRunMode, length=16), nullable=False)
    status: Mapped[CodeRunStatus] = mapped_column(
        _enum(CodeRunStatus, length=32), nullable=False, index=True
    )
    policy_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    trace_frames: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    evidence_event_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("evidence_events.event_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class CodeRunStatusHistory(Base):
    __tablename__ = "code_run_status_history"

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("code_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[CodeRunStatus | None] = mapped_column(
        _enum(CodeRunStatus, length=32), nullable=True
    )
    to_status: Mapped[CodeRunStatus] = mapped_column(
        _enum(CodeRunStatus, length=32), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = _created_at()


class TestResult(Base):
    __tablename__ = "test_results"
    __table_args__ = (
        UniqueConstraint("code_run_id", "ordinal", name="uq_test_result_ordinal"),
        UniqueConstraint(
            "code_run_id",
            "visibility",
            "case_id",
            name="uq_test_result_case",
        ),
        CheckConstraint("ordinal >= 1", name="ck_test_result_ordinal_positive"),
        CheckConstraint("duration_ms >= 0", name="ck_test_result_duration_nonnegative"),
        CheckConstraint("octet_length(stdout) <= 32768", name="ck_test_result_stdout_bytes"),
        CheckConstraint("octet_length(stderr) <= 32768", name="ck_test_result_stderr_bytes"),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("code_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(nullable=False)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    visibility: Mapped[TestVisibility] = mapped_column(
        _enum(TestVisibility, length=16), nullable=False
    )
    comparison: Mapped[SandboxComparison] = mapped_column(
        _enum(SandboxComparison, length=16), nullable=False
    )
    transfer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    stdout: Mapped[str] = mapped_column(Text, default="", nullable=False)
    stderr: Mapped[str] = mapped_column(Text, default="", nullable=False)
    stdout_truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    stderr_truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duration_ms: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = _created_at()


class HintUsage(Base):
    __tablename__ = "hint_usages"
    __table_args__ = (
        UniqueConstraint("task_instance_id", "sequence", name="uq_hint_usage_sequence"),
        CheckConstraint("sequence >= 1", name="ck_hint_usage_sequence_positive"),
        CheckConstraint("level >= 1 AND level <= 3", name="ck_hint_usage_level_range"),
        CheckConstraint("cost >= 0.0 AND cost <= 100.0", name="ck_hint_usage_cost_range"),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_instance_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("task_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("code_revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    hint_key: Mapped[str] = mapped_column(String(128), nullable=False)
    level: Mapped[int] = mapped_column(nullable=False)
    cost: Mapped[float] = mapped_column(Float, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[HintSource] = mapped_column(
        _enum(HintSource, length=32), default=HintSource.STATIC, nullable=False
    )
    created_at: Mapped[datetime] = _created_at()
