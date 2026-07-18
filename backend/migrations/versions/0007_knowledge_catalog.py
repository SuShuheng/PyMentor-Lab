"""Introduce the governed BE-009 knowledge catalogue.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import Uuid

revision: str = "0007"
down_revision: str = "0006"
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
        "course_catalog",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("audience", sa.String(512), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("content_version", sa.String(32), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("chapter_ids", postgresql.JSONB, nullable=False),
        sa.Column("deep_unit_node_ids", postgresql.JSONB, nullable=False),
        sa.Column("published", sa.Boolean, nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint("slug", name="uq_course_catalog_slug"),
        sa.UniqueConstraint("source_digest", name="uq_course_catalog_source_digest"),
    )
    op.create_table(
        "course_chapters",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column(
            "course_id",
            Uuid,
            sa.ForeignKey("course_catalog.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("learning_objectives", postgresql.JSONB, nullable=False),
        sa.Column("content_version", sa.String(32), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("course_id", "sequence", name="uq_course_chapters_sequence"),
        sa.CheckConstraint("sequence >= 1", name="ck_course_chapters_sequence_positive"),
    )
    op.create_index("ix_course_chapters_course_id", "course_chapters", ["course_id"])
    op.create_table(
        "knowledge_sources",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("publisher", sa.String(128), nullable=False),
        sa.Column("content_scope", sa.String(512), nullable=False),
        sa.Column("content_version", sa.String(32), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "knowledge_mastery_policies",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("pass_threshold", sa.Float, nullable=False),
        sa.Column("stable_attempts", sa.Integer, nullable=False),
        sa.Column("max_support_level", sa.Integer, nullable=False),
        sa.Column("min_transfer_score", sa.Float, nullable=False),
        sa.Column("review_intervals_days", postgresql.JSONB, nullable=False),
        sa.Column("content_version", sa.String(32), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "pass_threshold >= 0 AND pass_threshold <= 1",
            name="ck_knowledge_mastery_pass_threshold",
        ),
        sa.CheckConstraint(
            "stable_attempts >= 1", name="ck_knowledge_mastery_stable_attempts"
        ),
        sa.CheckConstraint(
            "max_support_level >= 0 AND max_support_level <= 3",
            name="ck_knowledge_mastery_support_level",
        ),
        sa.CheckConstraint(
            "min_transfer_score >= 0 AND min_transfer_score <= 1",
            name="ck_knowledge_mastery_transfer_score",
        ),
    )
    op.create_table(
        "knowledge_nodes",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column(
            "course_id",
            Uuid,
            sa.ForeignKey("course_catalog.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chapter_id",
            Uuid,
            sa.ForeignKey("course_chapters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("learning_objectives", postgresql.JSONB, nullable=False),
        sa.Column("prerequisites", postgresql.JSONB, nullable=False),
        sa.Column("misconceptions", postgresql.JSONB, nullable=False),
        sa.Column("examples", postgresql.JSONB, nullable=False),
        sa.Column("diagnostic_items", postgresql.JSONB, nullable=False),
        sa.Column("practice_templates", postgresql.JSONB, nullable=False),
        sa.Column(
            "mastery_policy_id",
            Uuid,
            sa.ForeignKey("knowledge_mastery_policies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_ids", postgresql.JSONB, nullable=False),
        sa.Column("content_version", sa.String(32), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("id", "course_id", name="uq_knowledge_nodes_id_course"),
    )
    op.create_index("ix_knowledge_nodes_course_id", "knowledge_nodes", ["course_id"])
    op.create_index("ix_knowledge_nodes_chapter_id", "knowledge_nodes", ["chapter_id"])
    op.create_index(
        "ix_knowledge_nodes_mastery_policy_id", "knowledge_nodes", ["mastery_policy_id"]
    )
    op.create_table(
        "knowledge_error_patterns",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("node_ids", postgresql.JSONB, nullable=False),
        sa.Column("symptom", sa.String(1024), nullable=False),
        sa.Column("misconception", sa.String(1024), nullable=False),
        sa.Column("diagnosis_prompts", postgresql.JSONB, nullable=False),
        sa.Column("remediation", postgresql.JSONB, nullable=False),
        sa.Column("source_ids", postgresql.JSONB, nullable=False),
        sa.Column("content_version", sa.String(32), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "knowledge_question_templates",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column(
            "node_id",
            Uuid,
            sa.ForeignKey("knowledge_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("prompt_template", sa.String(2048), nullable=False),
        sa.Column("parameter_schema", postgresql.JSONB, nullable=False),
        sa.Column("answer_schema", postgresql.JSONB, nullable=False),
        sa.Column("test_case_ids", postgresql.JSONB, nullable=False),
        sa.Column("source_ids", postgresql.JSONB, nullable=False),
        sa.Column("content_version", sa.String(32), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_knowledge_question_templates_node_id",
        "knowledge_question_templates",
        ["node_id"],
    )
    op.create_table(
        "knowledge_test_cases",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column(
            "node_id",
            Uuid,
            sa.ForeignKey("knowledge_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("input", sa.String(4096), nullable=False),
        sa.Column("expected", sa.String(4096), nullable=False),
        sa.Column("hidden", sa.Boolean, nullable=False),
        sa.Column("timeout_ms", sa.Integer, nullable=False),
        sa.Column("content_version", sa.String(32), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "timeout_ms >= 100 AND timeout_ms <= 10000",
            name="ck_knowledge_test_cases_timeout",
        ),
    )
    op.create_index("ix_knowledge_test_cases_node_id", "knowledge_test_cases", ["node_id"])

    op.create_foreign_key(
        "fk_learning_paths_course_catalog",
        "learning_paths",
        "course_catalog",
        ["course_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_learning_path_steps_knowledge_node",
        "learning_path_steps",
        "knowledge_nodes",
        ["node_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    for name, table in (
        ("fk_task_definitions_course_node", "task_definitions"),
        ("fk_assessment_results_course_node", "assessment_results"),
        ("fk_mastery_states_course_node", "mastery_states"),
        ("fk_review_schedules_course_node", "review_schedules"),
    ):
        op.create_foreign_key(
            name,
            table,
            "knowledge_nodes",
            ["node_id", "course_id"],
            ["id", "course_id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    for name, table in (
        ("fk_review_schedules_course_node", "review_schedules"),
        ("fk_mastery_states_course_node", "mastery_states"),
        ("fk_assessment_results_course_node", "assessment_results"),
        ("fk_task_definitions_course_node", "task_definitions"),
        ("fk_learning_path_steps_knowledge_node", "learning_path_steps"),
        ("fk_learning_paths_course_catalog", "learning_paths"),
    ):
        op.drop_constraint(name, table, type_="foreignkey")

    op.drop_table("knowledge_test_cases")
    op.drop_table("knowledge_question_templates")
    op.drop_table("knowledge_error_patterns")
    op.drop_table("knowledge_nodes")
    op.drop_table("knowledge_mastery_policies")
    op.drop_table("knowledge_sources")
    op.drop_table("course_chapters")
    op.drop_table("course_catalog")
