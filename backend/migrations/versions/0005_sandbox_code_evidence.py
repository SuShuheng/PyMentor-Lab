"""Sandbox code revisions, runs, test results, and hint evidence.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import Uuid

revision: str = "0005"
down_revision: str = "0004"
branch_labels = None
depends_on = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade() -> None:
    op.create_table(
        "code_revisions",
        sa.Column("id", Uuid, primary_key=True),
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
            "task_instance_id",
            Uuid,
            sa.ForeignKey("task_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column(
            "parent_revision_id",
            Uuid,
            sa.ForeignKey("code_revisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_code", sa.Text, nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        _created_at(),
        sa.UniqueConstraint("task_instance_id", "sequence", name="uq_code_revision_sequence"),
        sa.UniqueConstraint("task_instance_id", "source_digest", name="uq_code_revision_digest"),
        sa.CheckConstraint("sequence >= 1", name="ck_code_revision_sequence_positive"),
        sa.CheckConstraint(
            "octet_length(source_code) BETWEEN 1 AND 65536",
            name="ck_code_revision_source_bytes",
        ),
    )
    op.create_index("ix_code_revisions_tenant_id", "code_revisions", ["tenant_id"])
    op.create_index("ix_code_revisions_student_id", "code_revisions", ["student_id"])
    op.create_index("ix_code_revisions_task_instance_id", "code_revisions", ["task_instance_id"])
    op.create_index(
        "ix_code_revisions_parent_revision_id", "code_revisions", ["parent_revision_id"]
    )

    op.create_table(
        "code_runs",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False),
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
            "task_instance_id",
            Uuid,
            sa.ForeignKey("task_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "revision_id",
            Uuid,
            sa.ForeignKey("code_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "idempotency_key_id",
            Uuid,
            sa.ForeignKey("idempotency_keys.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("result", postgresql.JSONB, nullable=True),
        sa.Column("trace_frames", postgresql.JSONB, nullable=True),
        sa.Column(
            "evidence_event_id",
            sa.String(128),
            sa.ForeignKey("evidence_events.event_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_code_runs_run_id"),
        sa.UniqueConstraint("idempotency_key_id", name="uq_code_runs_idempotency_key"),
        sa.CheckConstraint("version >= 1", name="ck_code_run_version_positive"),
    )
    op.create_index("ix_code_runs_tenant_id", "code_runs", ["tenant_id"])
    op.create_index("ix_code_runs_student_id", "code_runs", ["student_id"])
    op.create_index("ix_code_runs_task_instance_id", "code_runs", ["task_instance_id"])
    op.create_index("ix_code_runs_revision_id", "code_runs", ["revision_id"])
    op.create_index("ix_code_runs_status", "code_runs", ["status"])
    op.create_index("ix_code_runs_evidence_event_id", "code_runs", ["evidence_event_id"])
    op.create_index("ix_code_runs_deadline_at", "code_runs", ["deadline_at"])
    op.create_index(
        "uq_code_run_active_task",
        "code_runs",
        ["task_instance_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
    )

    op.create_table(
        "code_run_status_history",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column(
            "tenant_id",
            Uuid,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "code_run_id",
            Uuid,
            sa.ForeignKey("code_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=False),
        _created_at(),
    )
    op.create_index(
        "ix_code_run_status_history_tenant_id",
        "code_run_status_history",
        ["tenant_id"],
    )
    op.create_index(
        "ix_code_run_status_history_code_run_id",
        "code_run_status_history",
        ["code_run_id"],
    )
    op.create_index(
        "ix_code_run_status_history_trace_id",
        "code_run_status_history",
        ["trace_id"],
    )

    op.create_table(
        "test_results",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column(
            "tenant_id",
            Uuid,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "code_run_id",
            Uuid,
            sa.ForeignKey("code_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("case_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("comparison", sa.String(16), nullable=False),
        sa.Column("transfer", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("message", sa.String(2000), nullable=True),
        sa.Column("stdout", sa.Text, nullable=False, server_default=""),
        sa.Column("stderr", sa.Text, nullable=False, server_default=""),
        sa.Column("stdout_truncated", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("stderr_truncated", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        _created_at(),
        sa.UniqueConstraint("code_run_id", "ordinal", name="uq_test_result_ordinal"),
        sa.UniqueConstraint(
            "code_run_id",
            "visibility",
            "case_id",
            name="uq_test_result_case",
        ),
        sa.CheckConstraint("ordinal >= 1", name="ck_test_result_ordinal_positive"),
        sa.CheckConstraint("duration_ms >= 0", name="ck_test_result_duration_nonnegative"),
        sa.CheckConstraint("octet_length(stdout) <= 32768", name="ck_test_result_stdout_bytes"),
        sa.CheckConstraint("octet_length(stderr) <= 32768", name="ck_test_result_stderr_bytes"),
    )
    op.create_index("ix_test_results_tenant_id", "test_results", ["tenant_id"])
    op.create_index("ix_test_results_code_run_id", "test_results", ["code_run_id"])

    op.create_table(
        "hint_usages",
        sa.Column("id", Uuid, primary_key=True),
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
            "task_instance_id",
            Uuid,
            sa.ForeignKey("task_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "revision_id",
            Uuid,
            sa.ForeignKey("code_revisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("hint_key", sa.String(128), nullable=False),
        sa.Column("level", sa.Integer, nullable=False),
        sa.Column("cost", sa.Float, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="STATIC"),
        _created_at(),
        sa.UniqueConstraint("task_instance_id", "sequence", name="uq_hint_usage_sequence"),
        sa.CheckConstraint("sequence >= 1", name="ck_hint_usage_sequence_positive"),
        sa.CheckConstraint("level >= 1 AND level <= 3", name="ck_hint_usage_level_range"),
        sa.CheckConstraint("cost >= 0.0 AND cost <= 100.0", name="ck_hint_usage_cost_range"),
    )
    op.create_index("ix_hint_usages_tenant_id", "hint_usages", ["tenant_id"])
    op.create_index("ix_hint_usages_student_id", "hint_usages", ["student_id"])
    op.create_index("ix_hint_usages_task_instance_id", "hint_usages", ["task_instance_id"])
    op.create_index("ix_hint_usages_revision_id", "hint_usages", ["revision_id"])


def downgrade() -> None:
    op.drop_table("hint_usages")
    op.drop_table("test_results")
    op.drop_table("code_run_status_history")
    op.drop_table("code_runs")
    op.drop_table("code_revisions")
