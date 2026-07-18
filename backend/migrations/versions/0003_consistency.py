"""Consistency tables: evidence, audit, outbox, idempotency.

设计 §15.1 第 8 组 + 证据表组。BE-003 在 BE-002 的 DB 基础上建立一致性基础设施。

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import Uuid

revision: str = "0003"
down_revision: str = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- evidence_events (append-only, event_id 唯一去重) ----
    op.create_table(
        "evidence_events",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column("student_id", Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("course_id", Uuid, nullable=True),
        sa.Column("node_id", Uuid, nullable=True),
        sa.Column("task_id", Uuid, nullable=True),
        sa.Column("agent_run_id", Uuid, nullable=True),
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evidence_confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_evidence_event_id"),
        sa.CheckConstraint(
            "evidence_confidence >= 0.0 AND evidence_confidence <= 1.0",
            name="ck_evidence_confidence_range",
        ),
    )
    op.create_index("ix_evidence_events_tenant_id", "evidence_events", ["tenant_id"])
    op.create_index("ix_evidence_events_student_id", "evidence_events", ["student_id"])
    op.create_index("ix_evidence_events_event_type", "evidence_events", ["event_type"])
    op.create_index("ix_evidence_events_course_id", "evidence_events", ["course_id"])
    op.create_index("ix_evidence_events_node_id", "evidence_events", ["node_id"])
    op.create_index("ix_evidence_events_task_id", "evidence_events", ["task_id"])
    op.create_index("ix_evidence_events_created_at", "evidence_events", ["created_at"])

    # ---- audit_events (append-only 审计) ----
    op.create_table(
        "audit_events",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column("actor_user_id", Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column("detail", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])

    # ---- outbox_events (事务性 Outbox, event_id 唯一幂等消费) ----
    op.create_table(
        "outbox_events",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("published", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_outbox_event_id"),
    )
    op.create_index("ix_outbox_events_tenant_id", "outbox_events", ["tenant_id"])
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_published", "outbox_events", ["published"])
    op.create_index("ix_outbox_events_created_at", "outbox_events", ["created_at"])

    # ---- idempotency_keys (API 命令幂等) ----
    op.create_table(
        "idempotency_keys",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column("user_id", Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("response_status", sa.Integer, nullable=True),
        sa.Column("response_body", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", name="uq_idempotency_keys_key"),
    )
    op.create_index("ix_idempotency_keys_tenant_id", "idempotency_keys", ["tenant_id"])
    op.create_index("ix_idempotency_keys_expires_at", "idempotency_keys", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_expires_at", table_name="idempotency_keys")
    op.drop_index("ix_idempotency_keys_tenant_id", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")

    op.drop_index("ix_outbox_events_created_at", table_name="outbox_events")
    op.drop_index("ix_outbox_events_published", table_name="outbox_events")
    op.drop_index("ix_outbox_events_event_type", table_name="outbox_events")
    op.drop_index("ix_outbox_events_tenant_id", table_name="outbox_events")
    op.drop_table("outbox_events")

    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_id", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_evidence_events_created_at", table_name="evidence_events")
    op.drop_index("ix_evidence_events_event_type", table_name="evidence_events")
    op.drop_index(
        "ix_evidence_events_task_id", table_name="evidence_events", if_exists=True
    )
    op.drop_index(
        "ix_evidence_events_node_id", table_name="evidence_events", if_exists=True
    )
    op.drop_index(
        "ix_evidence_events_course_id", table_name="evidence_events", if_exists=True
    )
    op.drop_index("ix_evidence_events_student_id", table_name="evidence_events")
    op.drop_index("ix_evidence_events_tenant_id", table_name="evidence_events")
    op.drop_table("evidence_events")
