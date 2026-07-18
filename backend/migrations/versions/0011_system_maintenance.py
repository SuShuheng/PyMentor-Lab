"""Add database backup and maintenance operation records.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.types import Uuid

revision: str = "0011"
down_revision: str = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "database_backups",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column("object_key", sa.String(255), nullable=False, unique=True),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_by",
            Uuid,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_database_backups_size_nonnegative"),
        sa.CheckConstraint("length(digest) = 64", name="ck_database_backups_digest_length"),
        sa.CheckConstraint(
            "status IN ('AVAILABLE', 'INVALID')", name="ck_database_backups_status"
        ),
    )
    for column in ("tenant_id", "created_by", "created_at"):
        op.create_index(f"ix_database_backups_{column}", "database_backups", [column])

    op.create_table(
        "maintenance_operations",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column("operation_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "backup_id",
            Uuid,
            sa.ForeignKey("database_backups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "requested_by",
            Uuid,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "operation_type IN ('DATABASE_BACKUP', 'DATABASE_RESTORE', "
            "'DEMO_TENANT_RESET', 'STUDENT_DELETE')",
            name="ck_maintenance_operations_type",
        ),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED', 'FAILED')",
            name="ck_maintenance_operations_status",
        ),
    )
    for column in (
        "tenant_id",
        "operation_type",
        "status",
        "requested_by",
        "trace_id",
        "created_at",
    ):
        op.create_index(
            f"ix_maintenance_operations_{column}", "maintenance_operations", [column]
        )


def downgrade() -> None:
    op.drop_table("maintenance_operations")
    op.drop_table("database_backups")
