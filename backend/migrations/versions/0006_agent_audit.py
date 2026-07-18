"""Persist normalized, redacted agent workflow audit.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import Uuid

revision: str = "0006"
down_revision: str = "0005"
branch_labels = None
depends_on = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def upgrade() -> None:
    op.create_table(
        "agent_definitions",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("allowed_tools", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("policy_snapshot", postgresql.JSONB, nullable=False, server_default="{}"),
        _created_at(),
        sa.UniqueConstraint("name", "version", name="uq_agent_definitions_name_version"),
        sa.CheckConstraint("version >= 1", name="ck_agent_definitions_version_positive"),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("external_run_id", sa.String(128), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column(
            "tenant_id",
            Uuid,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            Uuid,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "definition_id",
            Uuid,
            sa.ForeignKey("agent_definitions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="QUEUED"),
        sa.Column("route", sa.String(32), nullable=True),
        sa.Column("latest_sequence", sa.Integer, nullable=False, server_default="0"),
        sa.Column("checkpoint_thread_id", sa.String(128), nullable=True),
        sa.Column("latest_checkpoint_id", sa.String(128), nullable=True),
        sa.Column("fallback_used", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("safe_input_snapshot", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("safe_output_snapshot", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("event_id", name="uq_agent_runs_event_id"),
        sa.UniqueConstraint("external_run_id", name="uq_agent_runs_external_run_id"),
        sa.CheckConstraint(
            "latest_sequence >= 0", name="ck_agent_runs_latest_sequence_nonnegative"
        ),
    )
    op.create_index("ix_agent_runs_trace_id", "agent_runs", ["trace_id"])
    op.create_index("ix_agent_runs_tenant_id", "agent_runs", ["tenant_id"])
    op.create_index("ix_agent_runs_student_id", "agent_runs", ["student_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column(
            "tenant_id",
            Uuid,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_run_id",
            Uuid,
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("node", sa.String(32), nullable=True),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("argument_digest", sa.String(64), nullable=True),
        sa.Column("result_digest", sa.String(64), nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.UniqueConstraint("agent_run_id", "sequence", name="uq_agent_tool_calls_run_sequence"),
        sa.CheckConstraint("sequence >= 1", name="ck_agent_tool_calls_sequence_positive"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_agent_tool_calls_latency_nonnegative"),
        sa.CheckConstraint("retry_count >= 0", name="ck_agent_tool_calls_retry_nonnegative"),
    )
    op.create_index("ix_agent_tool_calls_tenant_id", "agent_tool_calls", ["tenant_id"])
    op.create_index("ix_agent_tool_calls_agent_run_id", "agent_tool_calls", ["agent_run_id"])


def downgrade() -> None:
    op.drop_table("agent_tool_calls")
    op.drop_table("agent_runs")
    op.drop_table("agent_definitions")
