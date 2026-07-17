"""Identity and RBAC tables.

Creates the users/roles/tenants group (frozen design §15.1 migration order #1).
BE-002 owns this group; BE-003 adds evidence/audit/Outbox/idempotency later.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.types import Uuid

revision: str = "0002"
down_revision: str = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- roles (dictionary, created before users so FK works) ----
    op.create_table(
        "roles",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )

    # ---- tenants ----
    op.create_table(
        "tenants",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(32), nullable=False, server_default="STANDARD"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    # ---- users ----
    op.create_table(
        "users",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("student_no", sa.String(64), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        sa.UniqueConstraint("tenant_id", "student_no", name="uq_users_tenant_student_no"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    # ---- user_roles ----
    op.create_table(
        "user_roles",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("user_id", Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", Uuid, sa.ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])

    # ---- user_sessions (refresh token rotation + reuse detection) ----
    op.create_table(
        "user_sessions",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("user_id", Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jti", sa.String(64), nullable=False),
        sa.Column("token_type", sa.String(16), nullable=False, server_default="REFRESH"),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("jti", name="uq_user_sessions_jti"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_jti", "user_sessions", ["jti"])


def downgrade() -> None:
    op.drop_index("ix_user_sessions_jti", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")

    op.drop_index("ix_user_roles_role_id", table_name="user_roles")
    op.drop_index("ix_user_roles_user_id", table_name="user_roles")
    op.drop_table("user_roles")

    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")

    op.drop_table("tenants")
    op.drop_table("roles")
