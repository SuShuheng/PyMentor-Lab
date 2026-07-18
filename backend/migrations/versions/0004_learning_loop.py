"""Deterministic learning-loop tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import Uuid

revision: str = "0004"
down_revision: str = "0003"
branch_labels = None
depends_on = None


def _json_object() -> sa.TextClause:
    return sa.text("'{}'::jsonb")


def _json_array() -> sa.TextClause:
    return sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.create_table(
        "learning_contexts",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "student_id",
            Uuid,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("goal", sa.String(512), nullable=True),
        sa.Column("background", sa.String(1024), nullable=True),
        sa.Column("progress", postgresql.JSONB, nullable=False, server_default=_json_object()),
        sa.Column("daily_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "media_preferences", postgresql.JSONB, nullable=False, server_default=_json_object()
        ),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mode", sa.String(64), nullable=True),
        sa.Column(
            "device_constraints", postgresql.JSONB, nullable=False, server_default=_json_object()
        ),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("student_id", name="uq_learning_context_student"),
        sa.CheckConstraint(
            "daily_minutes >= 0", name="ck_learning_context_daily_minutes_nonnegative"
        ),
        sa.CheckConstraint("version >= 1", name="ck_learning_context_version_positive"),
    )
    op.create_index("ix_learning_contexts_tenant_id", "learning_contexts", ["tenant_id"])
    op.create_index("ix_learning_contexts_student_id", "learning_contexts", ["student_id"])

    op.create_table(
        "profile_versions",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "student_id",
            Uuid,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("student_id", "version", name="uq_profile_student_version"),
        sa.UniqueConstraint(
            "student_id", "source_event_id", name="uq_profile_student_source_event"
        ),
        sa.CheckConstraint("version >= 1", name="ck_profile_version_positive"),
    )
    op.create_index("ix_profile_versions_tenant_id", "profile_versions", ["tenant_id"])
    op.create_index("ix_profile_versions_student_id", "profile_versions", ["student_id"])

    op.create_table(
        "profile_dimension_scores",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "profile_version_id",
            Uuid,
            sa.ForeignKey("profile_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dimension", sa.String(32), nullable=False),
        sa.Column("scope_key", sa.String(128), nullable=False, server_default="GLOBAL"),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("support_level", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "profile_version_id",
            "dimension",
            "scope_key",
            name="uq_profile_dimension_scope",
        ),
        sa.CheckConstraint(
            "score >= 0.0 AND score <= 1.0", name="ck_profile_dimension_score_range"
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_profile_dimension_confidence_range",
        ),
        sa.CheckConstraint(
            "support_level >= 0 AND support_level <= 3",
            name="ck_profile_dimension_support_level_range",
        ),
    )
    op.create_index(
        "ix_profile_dimension_scores_tenant_id", "profile_dimension_scores", ["tenant_id"]
    )
    op.create_index(
        "ix_profile_dimension_scores_profile_version_id",
        "profile_dimension_scores",
        ["profile_version_id"],
    )

    op.create_table(
        "profile_change_proposals",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "student_id",
            Uuid,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_event_id", sa.String(128), nullable=True),
        sa.Column("proposer_type", sa.String(32), nullable=False),
        sa.Column("expected_version", sa.Integer, nullable=False),
        sa.Column("updates", postgresql.JSONB, nullable=False),
        sa.Column("rationale", sa.String(1024), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PROPOSED"),
        sa.Column(
            "accepted_profile_version_id",
            Uuid,
            sa.ForeignKey("profile_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expected_version >= 0", name="ck_profile_proposal_expected_version"
        ),
        sa.CheckConstraint("version >= 1", name="ck_profile_proposal_version_positive"),
    )
    op.create_index(
        "ix_profile_change_proposals_tenant_id", "profile_change_proposals", ["tenant_id"]
    )
    op.create_index(
        "ix_profile_change_proposals_student_id", "profile_change_proposals", ["student_id"]
    )
    op.create_index(
        "ix_profile_change_proposals_status", "profile_change_proposals", ["status"]
    )

    op.create_table(
        "profile_disputes",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "student_id",
            Uuid,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_version_id",
            Uuid,
            sa.ForeignKey("profile_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_profile_disputes_tenant_id", "profile_disputes", ["tenant_id"])
    op.create_index("ix_profile_disputes_student_id", "profile_disputes", ["student_id"])
    op.create_index(
        "ix_profile_disputes_profile_version_id", "profile_disputes", ["profile_version_id"]
    )

    op.create_table(
        "learning_paths",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "student_id",
            Uuid,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_id", Uuid, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="CURRENT"),
        sa.Column(
            "source_proposal", postgresql.JSONB, nullable=False, server_default=_json_object()
        ),
        sa.Column(
            "validation_findings", postgresql.JSONB, nullable=False, server_default=_json_array()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "student_id", "course_id", "version", name="uq_learning_path_version"
        ),
        sa.CheckConstraint("version >= 1", name="ck_learning_path_version_positive"),
    )
    op.create_index("ix_learning_paths_tenant_id", "learning_paths", ["tenant_id"])
    op.create_index("ix_learning_paths_student_id", "learning_paths", ["student_id"])
    op.create_index("ix_learning_paths_course_id", "learning_paths", ["course_id"])
    op.create_index("ix_learning_paths_status", "learning_paths", ["status"])
    op.create_index(
        "uq_learning_path_current",
        "learning_paths",
        ["student_id", "course_id"],
        unique=True,
        postgresql_where=sa.text("status = 'CURRENT'"),
    )

    op.create_table(
        "learning_path_steps",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "path_id",
            Uuid,
            sa.ForeignKey("learning_paths.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("node_id", Uuid, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("estimated_minutes", sa.Integer, nullable=False),
        sa.Column("scenario_key", sa.String(128), nullable=False),
        sa.Column(
            "source_metadata", postgresql.JSONB, nullable=False, server_default=_json_object()
        ),
        sa.Column("validation_status", sa.String(16), nullable=False),
        sa.Column(
            "validation_outcome", postgresql.JSONB, nullable=False, server_default=_json_object()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("path_id", "position", name="uq_learning_path_step_position"),
        sa.CheckConstraint("position >= 1", name="ck_learning_path_step_position_positive"),
        sa.CheckConstraint(
            "estimated_minutes >= 1", name="ck_learning_path_step_minutes_positive"
        ),
    )
    op.create_index("ix_learning_path_steps_tenant_id", "learning_path_steps", ["tenant_id"])
    op.create_index("ix_learning_path_steps_path_id", "learning_path_steps", ["path_id"])
    op.create_index("ix_learning_path_steps_node_id", "learning_path_steps", ["node_id"])

    op.create_table(
        "task_definitions",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column("course_id", Uuid, nullable=False),
        sa.Column("node_id", Uuid, nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "course_id", "key", name="uq_task_definition_key"),
        sa.CheckConstraint("version >= 1", name="ck_task_definition_version_positive"),
    )
    op.create_index("ix_task_definitions_tenant_id", "task_definitions", ["tenant_id"])
    op.create_index("ix_task_definitions_course_id", "task_definitions", ["course_id"])
    op.create_index("ix_task_definitions_node_id", "task_definitions", ["node_id"])

    op.create_table(
        "task_versions",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "definition_id",
            Uuid,
            sa.ForeignKey("task_definitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("snapshot", postgresql.JSONB, nullable=False),
        sa.Column("snapshot_digest", sa.String(64), nullable=False),
        sa.Column("scenario_key", sa.String(128), nullable=False),
        sa.Column("published", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("definition_id", "version", name="uq_task_version_number"),
        sa.UniqueConstraint("definition_id", "snapshot_digest", name="uq_task_version_digest"),
        sa.CheckConstraint("version >= 1", name="ck_task_version_positive"),
    )
    op.create_index("ix_task_versions_tenant_id", "task_versions", ["tenant_id"])
    op.create_index("ix_task_versions_definition_id", "task_versions", ["definition_id"])
    op.create_index("ix_task_versions_scenario_key", "task_versions", ["scenario_key"])
    op.create_index("ix_task_versions_published", "task_versions", ["published"])

    op.create_table(
        "task_instances",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "student_id",
            Uuid,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_version_id",
            Uuid,
            sa.ForeignKey("task_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("active_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("snapshot", postgresql.JSONB, nullable=False),
        sa.Column("snapshot_digest", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("version >= 1", name="ck_task_instance_version_positive"),
    )
    op.create_index("ix_task_instances_tenant_id", "task_instances", ["tenant_id"])
    op.create_index("ix_task_instances_student_id", "task_instances", ["student_id"])
    op.create_index("ix_task_instances_task_version_id", "task_instances", ["task_version_id"])
    op.create_index("ix_task_instances_status", "task_instances", ["status"])
    op.create_index(
        "uq_task_instance_active",
        "task_instances",
        ["student_id", "task_version_id", "active_key"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "task_status_history",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "task_instance_id",
            Uuid,
            sa.ForeignKey("task_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("evidence_event_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_task_status_history_tenant_id", "task_status_history", ["tenant_id"])
    op.create_index(
        "ix_task_status_history_task_instance_id",
        "task_status_history",
        ["task_instance_id"],
    )

    op.create_table(
        "assessment_results",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "student_id",
            Uuid,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_id", Uuid, nullable=False),
        sa.Column("node_id", Uuid, nullable=False),
        sa.Column(
            "task_instance_id",
            Uuid,
            sa.ForeignKey("task_instances.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("evidence_event_id", sa.String(128), nullable=False),
        sa.Column("correct", sa.Boolean, nullable=False),
        sa.Column("hidden_tests_passed", sa.Boolean, nullable=False),
        sa.Column("hints_used", sa.Integer, nullable=False),
        sa.Column("support_level", sa.Integer, nullable=False),
        sa.Column("independence_score", sa.Float, nullable=False),
        sa.Column("transfer_score", sa.Float, nullable=False),
        sa.Column("platform_error", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("facts", postgresql.JSONB, nullable=False, server_default=_json_object()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("evidence_event_id", name="uq_assessment_evidence_event"),
        sa.CheckConstraint("hints_used >= 0", name="ck_assessment_hints_nonnegative"),
        sa.CheckConstraint(
            "support_level >= 0 AND support_level <= 3",
            name="ck_assessment_support_level_range",
        ),
        sa.CheckConstraint(
            "independence_score >= 0.0 AND independence_score <= 1.0",
            name="ck_assessment_independence_range",
        ),
        sa.CheckConstraint(
            "transfer_score >= 0.0 AND transfer_score <= 1.0",
            name="ck_assessment_transfer_range",
        ),
    )
    op.create_index("ix_assessment_results_tenant_id", "assessment_results", ["tenant_id"])
    op.create_index("ix_assessment_results_student_id", "assessment_results", ["student_id"])
    op.create_index("ix_assessment_results_course_id", "assessment_results", ["course_id"])
    op.create_index("ix_assessment_results_node_id", "assessment_results", ["node_id"])
    op.create_index(
        "ix_assessment_results_task_instance_id", "assessment_results", ["task_instance_id"]
    )

    op.create_table(
        "mastery_states",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "student_id",
            Uuid,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_id", Uuid, nullable=False),
        sa.Column("node_id", Uuid, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="UNSEEN"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("last_evidence_event_id", sa.String(128), nullable=True),
        sa.Column("initial_mastery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stable_mastery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "student_id", "course_id", "node_id", name="uq_mastery_student_course_node"
        ),
        sa.CheckConstraint("version >= 1", name="ck_mastery_state_version_positive"),
    )
    op.create_index("ix_mastery_states_tenant_id", "mastery_states", ["tenant_id"])
    op.create_index("ix_mastery_states_student_id", "mastery_states", ["student_id"])
    op.create_index("ix_mastery_states_course_id", "mastery_states", ["course_id"])
    op.create_index("ix_mastery_states_node_id", "mastery_states", ["node_id"])
    op.create_index("ix_mastery_states_status", "mastery_states", ["status"])

    op.create_table(
        "mastery_state_history",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "mastery_state_id",
            Uuid,
            sa.ForeignKey("mastery_states.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("evidence_event_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mastery_state_history_tenant_id", "mastery_state_history", ["tenant_id"])
    op.create_index(
        "ix_mastery_state_history_mastery_state_id",
        "mastery_state_history",
        ["mastery_state_id"],
    )

    op.create_table(
        "review_schedules",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "student_id",
            Uuid,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_id", Uuid, nullable=False),
        sa.Column("node_id", Uuid, nullable=False),
        sa.Column(
            "mastery_state_id",
            Uuid,
            sa.ForeignKey("mastery_states.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scenario_key", sa.String(128), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hint_ceiling", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="SCHEDULED"),
        sa.Column("reschedule_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_rescheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("hint_ceiling >= 0", name="ck_review_hint_ceiling_nonnegative"),
        sa.CheckConstraint(
            "reschedule_count >= 0", name="ck_review_reschedule_count_nonnegative"
        ),
        sa.CheckConstraint("version >= 1", name="ck_review_schedule_version_positive"),
    )
    op.create_index("ix_review_schedules_tenant_id", "review_schedules", ["tenant_id"])
    op.create_index("ix_review_schedules_student_id", "review_schedules", ["student_id"])
    op.create_index("ix_review_schedules_course_id", "review_schedules", ["course_id"])
    op.create_index("ix_review_schedules_node_id", "review_schedules", ["node_id"])
    op.create_index(
        "ix_review_schedules_mastery_state_id", "review_schedules", ["mastery_state_id"]
    )
    op.create_index("ix_review_schedules_due_at", "review_schedules", ["due_at"])
    op.create_index("ix_review_schedules_status", "review_schedules", ["status"])
    op.create_index(
        "uq_review_schedule_active",
        "review_schedules",
        ["student_id", "course_id", "node_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('SCHEDULED', 'DUE')"),
    )

    op.create_table(
        "review_attempts",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column("tenant_id", Uuid, nullable=False),
        sa.Column(
            "review_schedule_id",
            Uuid,
            sa.ForeignKey("review_schedules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assessment_result_id",
            Uuid,
            sa.ForeignKey("assessment_results.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("evidence_event_id", sa.String(128), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("scenario_key", sa.String(128), nullable=False),
        sa.Column("hints_used", sa.Integer, nullable=False),
        sa.Column("support_level", sa.Integer, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("evidence_event_id", name="uq_review_attempt_evidence_event"),
        sa.CheckConstraint("hints_used >= 0", name="ck_review_attempt_hints_nonnegative"),
        sa.CheckConstraint(
            "support_level >= 0 AND support_level <= 3",
            name="ck_review_attempt_support_level_range",
        ),
    )
    op.create_index("ix_review_attempts_tenant_id", "review_attempts", ["tenant_id"])
    op.create_index(
        "ix_review_attempts_review_schedule_id", "review_attempts", ["review_schedule_id"]
    )


def downgrade() -> None:
    op.drop_table("review_attempts")
    op.drop_table("review_schedules")
    op.drop_table("mastery_state_history")
    op.drop_table("mastery_states")
    op.drop_table("assessment_results")
    op.drop_table("task_status_history")
    op.drop_table("task_instances")
    op.drop_table("task_versions")
    op.drop_table("task_definitions")
    op.drop_table("learning_path_steps")
    op.drop_table("learning_paths")
    op.drop_table("profile_disputes")
    op.drop_table("profile_change_proposals")
    op.drop_table("profile_dimension_scores")
    op.drop_table("profile_versions")
    op.drop_table("learning_contexts")
