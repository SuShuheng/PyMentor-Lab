"""Persist BE-007 resource jobs, artifacts, objects, and review gates.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import Uuid

revision: str = "0008"
down_revision: str = "0007"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def upgrade() -> None:
    op.create_table(
        "resource_jobs",
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
        sa.Column("course_id", Uuid, nullable=False),
        sa.Column("node_id", Uuid, nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="QUEUED"),
        sa.Column("requested_types", postgresql.JSONB, nullable=False),
        sa.Column("source_ids", postgresql.JSONB, nullable=False),
        sa.Column("context_digest", sa.String(64), nullable=False),
        sa.Column("progress_percent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_resource_jobs_tenant_idempotency"
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_resource_jobs_progress_range",
        ),
        sa.ForeignKeyConstraint(
            ["node_id", "course_id"],
            ["knowledge_nodes.id", "knowledge_nodes.course_id"],
            name="fk_resource_jobs_course_node",
            ondelete="RESTRICT",
        ),
    )
    for column in ("tenant_id", "student_id", "course_id", "node_id", "status"):
        op.create_index(f"ix_resource_jobs_{column}", "resource_jobs", [column])

    op.create_table(
        "learning_resources",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column(
            "tenant_id",
            Uuid,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            Uuid,
            sa.ForeignKey("resource_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="STAGED"),
        sa.Column("source_ids", postgresql.JSONB, nullable=False),
        sa.Column("context_digest", sa.String(64), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "job_id",
            "resource_type",
            "version",
            name="uq_learning_resources_job_type_version",
        ),
        sa.CheckConstraint("version >= 1", name="ck_learning_resources_version_positive"),
    )
    for column in ("tenant_id", "job_id", "resource_type", "status"):
        op.create_index(f"ix_learning_resources_{column}", "learning_resources", [column])

    op.create_table(
        "resource_objects",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column(
            "resource_id",
            Uuid,
            sa.ForeignKey("learning_resources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("published", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("object_key", name="uq_resource_objects_key"),
        sa.UniqueConstraint(
            "resource_id", "version", name="uq_resource_objects_resource_version"
        ),
        sa.CheckConstraint("version >= 1", name="ck_resource_objects_version_positive"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_resource_objects_size_nonnegative"),
    )
    op.create_index("ix_resource_objects_resource_id", "resource_objects", ["resource_id"])
    op.create_index("ix_resource_objects_published", "resource_objects", ["published"])

    op.create_table(
        "resource_reviews",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column(
            "resource_id",
            Uuid,
            sa.ForeignKey("learning_resources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gate", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("findings", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("reviewer", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "resource_id",
            "gate",
            "version",
            name="uq_resource_reviews_resource_gate_version",
        ),
        sa.CheckConstraint("version >= 1", name="ck_resource_reviews_version_positive"),
    )
    op.create_index("ix_resource_reviews_resource_id", "resource_reviews", ["resource_id"])
    op.create_index("ix_resource_reviews_gate", "resource_reviews", ["gate"])


def downgrade() -> None:
    op.drop_table("resource_reviews")
    op.drop_table("resource_objects")
    op.drop_table("learning_resources")
    op.drop_table("resource_jobs")
