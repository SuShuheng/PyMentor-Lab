"""Add durable operational logs and Provider call metrics.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import Uuid

revision: str = "0010"
down_revision: str = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_logs",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("message", sa.String(255), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column("context_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for column in ("tenant_id", "source", "level", "trace_id", "created_at"):
        op.create_index(f"ix_operational_logs_{column}", "operational_logs", [column])

    op.create_table(
        "provider_call_records",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "provider_config_id",
            Uuid,
            sa.ForeignKey("provider_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("vendor", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rate_limited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "latency_ms >= 0", name="ck_provider_calls_latency_nonnegative"
        ),
        sa.CheckConstraint("input_units >= 0", name="ck_provider_calls_input_nonnegative"),
        sa.CheckConstraint("output_units >= 0", name="ck_provider_calls_output_nonnegative"),
    )
    for column in (
        "tenant_id",
        "provider_config_id",
        "provider_type",
        "operation",
        "outcome",
        "trace_id",
        "created_at",
    ):
        op.create_index(
            f"ix_provider_call_records_{column}", "provider_call_records", [column]
        )


def downgrade() -> None:
    op.drop_table("provider_call_records")
    op.drop_table("operational_logs")
