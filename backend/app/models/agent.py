"""Normalized, redacted persistence for BE-006 agent workflow audit."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import Uuid

from app.db import Base


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgentDefinition(Base):
    """Versioned public policy metadata; raw system prompts are never stored."""

    __tablename__ = "agent_definitions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_agent_definitions_name_version"),
        CheckConstraint("version >= 1", name="ck_agent_definitions_version_positive"),
    )

    id: Mapped[UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    allowed_tools: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class AgentRun(Base):
    """One durable row per external workflow event/run identity."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_agent_runs_event_id"),
        UniqueConstraint("external_run_id", name="uq_agent_runs_external_run_id"),
        CheckConstraint("latest_sequence >= 0", name="ck_agent_runs_latest_sequence_nonnegative"),
    )

    id: Mapped[UUID] = _uuid_pk()
    external_run_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    definition_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("agent_definitions.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", nullable=False, index=True)
    route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latest_sequence: Mapped[int] = mapped_column(default=0, nullable=False)
    checkpoint_thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latest_checkpoint_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    safe_input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    safe_output_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AgentToolCall(Base):
    """Redacted tool lifecycle event, unique within a run by audit sequence."""

    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        UniqueConstraint("agent_run_id", "sequence", name="uq_agent_tool_calls_run_sequence"),
        CheckConstraint("sequence >= 1", name="ck_agent_tool_calls_sequence_positive"),
        CheckConstraint("latency_ms >= 0", name="ck_agent_tool_calls_latency_nonnegative"),
        CheckConstraint("retry_count >= 0", name="ck_agent_tool_calls_retry_nonnegative"),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    node: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    argument_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int] = mapped_column(default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class AgentPromptTemplate(Base):
    """BE-020 versioned, tenant-scoped system prompt per LangGraph node.

    V1.0 hardcoded prompts inside the Worker; BE-020 externalizes them so a
    System Admin can version, audit, and publish prompt edits without a deploy.
    At most one row per ``(tenant_id, node)`` may have ``published = true``;
    publishing a new version atomically unpublishes the others. The Worker reads
    the published version at runtime (see api.agent_prompts contract).
    """

    __tablename__ = "agent_prompt_templates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "node",
            "version",
            name="uq_agent_prompt_templates_tenant_node_version",
        ),
        CheckConstraint("version >= 1", name="ck_agent_prompt_templates_version_positive"),
        CheckConstraint(
            "length(system_prompt) >= 1",
            name="ck_agent_prompt_templates_prompt_nonempty",
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    published: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=func.false(), index=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
