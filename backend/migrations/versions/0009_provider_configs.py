"""Add encrypted, tenant-scoped Provider configurations.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import Uuid

revision: str = "0009"
down_revision: str = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_configs",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column(
            "tenant_id",
            Uuid,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("vendor", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("api_key_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("endpoint", sa.String(2048), nullable=True),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "provider_type",
            "vendor",
            "model",
            name="uq_provider_configs_identity",
        ),
        sa.CheckConstraint("version >= 1", name="ck_provider_configs_version_positive"),
    )
    op.create_index("ix_provider_configs_tenant_id", "provider_configs", ["tenant_id"])
    op.create_index("ix_provider_configs_provider_type", "provider_configs", ["provider_type"])
    op.create_index("ix_provider_configs_enabled", "provider_configs", ["enabled"])
    op.create_index(
        "uq_provider_configs_enabled_type",
        "provider_configs",
        ["tenant_id", "provider_type"],
        unique=True,
        postgresql_where=sa.text("enabled"),
    )


def downgrade() -> None:
    op.drop_index("uq_provider_configs_enabled_type", table_name="provider_configs")
    op.drop_index("ix_provider_configs_enabled", table_name="provider_configs")
    op.drop_index("ix_provider_configs_provider_type", table_name="provider_configs")
    op.drop_index("ix_provider_configs_tenant_id", table_name="provider_configs")
    op.drop_table("provider_configs")
