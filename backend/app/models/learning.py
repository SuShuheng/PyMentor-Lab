"""Normalized persistence for the deterministic learning loop (BE-004).

Course and knowledge-node identifiers intentionally remain UUID references
without foreign keys until BE-009 introduces the governed course catalogue.
Current formal rows carry optimistic versions; history, assessment, dispute,
and review-attempt rows are append-only by service policy.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import Uuid

from app.db import Base


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProfileDimension(StrEnum):
    CONCEPT_KNOWLEDGE = "CONCEPT_KNOWLEDGE"
    EXECUTION_MODEL = "EXECUTION_MODEL"
    IMPLEMENTATION = "IMPLEMENTATION"
    DECOMPOSITION = "DECOMPOSITION"
    DEBUGGING = "DEBUGGING"
    TESTING = "TESTING"
    TRANSFER = "TRANSFER"
    INDEPENDENCE_SUPPORT = "INDEPENDENCE_SUPPORT"


class ProfileProposalStatus(StrEnum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class LearningPathStatus(StrEnum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class PathStepKind(StrEnum):
    REVIEW = "REVIEW"
    LEARN = "LEARN"
    PRACTICE = "PRACTICE"
    ASSESSMENT = "ASSESSMENT"


class PathValidationStatus(StrEnum):
    VALIDATED = "VALIDATED"
    REPAIRED = "REPAIRED"
    FALLBACK = "FALLBACK"


class TaskInstanceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MasteryStatus(StrEnum):
    UNSEEN = "UNSEEN"
    LEARNING = "LEARNING"
    PASSED_WITH_HELP = "PASSED_WITH_HELP"
    INITIAL_MASTERY = "INITIAL_MASTERY"
    STABLE_MASTERY = "STABLE_MASTERY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ReviewStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReviewAttemptOutcome(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    PLATFORM_ERROR = "PLATFORM_ERROR"


class LearningContext(Base):
    __tablename__ = "learning_contexts"
    __table_args__ = (
        UniqueConstraint("student_id", name="uq_learning_context_student"),
        CheckConstraint("daily_minutes >= 0", name="ck_learning_context_daily_minutes_nonnegative"),
        CheckConstraint("version >= 1", name="ck_learning_context_version_positive"),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    goal: Mapped[str | None] = mapped_column(String(512), nullable=True)
    background: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    daily_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    media_preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class ProfileVersion(Base):
    __tablename__ = "profile_versions"
    __table_args__ = (
        UniqueConstraint("student_id", "version", name="uq_profile_student_version"),
        UniqueConstraint("student_id", "source_event_id", name="uq_profile_student_source_event"),
        CheckConstraint("version >= 1", name="ck_profile_version_positive"),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class ProfileDimensionScore(Base):
    __tablename__ = "profile_dimension_scores"
    __table_args__ = (
        UniqueConstraint(
            "profile_version_id",
            "dimension",
            "scope_key",
            name="uq_profile_dimension_scope",
        ),
        CheckConstraint(
            "score >= 0.0 AND score <= 1.0",
            name="ck_profile_dimension_score_range",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_profile_dimension_confidence_range",
        ),
        CheckConstraint(
            "support_level >= 0 AND support_level <= 3",
            name="ck_profile_dimension_support_level_range",
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    profile_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("profile_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dimension: Mapped[ProfileDimension] = mapped_column(
        SqlEnum(ProfileDimension, native_enum=False, length=32), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(String(128), default="GLOBAL", nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    support_level: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = _created_at()


class ProfileChangeProposal(Base):
    __tablename__ = "profile_change_proposals"
    __table_args__ = (
        CheckConstraint("expected_version >= 0", name="ck_profile_proposal_expected_version"),
        CheckConstraint("version >= 1", name="ck_profile_proposal_version_positive"),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    proposer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_version: Mapped[int] = mapped_column(nullable=False)
    updates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[ProfileProposalStatus] = mapped_column(
        SqlEnum(ProfileProposalStatus, native_enum=False, length=16),
        default=ProfileProposalStatus.PROPOSED,
        nullable=False,
        index=True,
    )
    accepted_profile_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("profile_versions.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProfileDispute(Base):
    __tablename__ = "profile_disputes"

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("profile_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class LearningPath(Base):
    __tablename__ = "learning_paths"
    __table_args__ = (
        UniqueConstraint("student_id", "course_id", "version", name="uq_learning_path_version"),
        CheckConstraint("version >= 1", name="ck_learning_path_version_positive"),
        Index(
            "uq_learning_path_current",
            "student_id",
            "course_id",
            unique=True,
            postgresql_where=text("status = 'CURRENT'"),
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[LearningPathStatus] = mapped_column(
        SqlEnum(LearningPathStatus, native_enum=False, length=16),
        default=LearningPathStatus.CURRENT,
        nullable=False,
        index=True,
    )
    source_proposal: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    validation_findings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class LearningPathStep(Base):
    __tablename__ = "learning_path_steps"
    __table_args__ = (
        UniqueConstraint("path_id", "position", name="uq_learning_path_step_position"),
        CheckConstraint("position >= 1", name="ck_learning_path_step_position_positive"),
        CheckConstraint("estimated_minutes >= 1", name="ck_learning_path_step_minutes_positive"),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    path_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("learning_paths.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(nullable=False)
    node_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    kind: Mapped[PathStepKind] = mapped_column(
        SqlEnum(PathStepKind, native_enum=False, length=16), nullable=False
    )
    estimated_minutes: Mapped[int] = mapped_column(nullable=False)
    scenario_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    validation_status: Mapped[PathValidationStatus] = mapped_column(
        SqlEnum(PathValidationStatus, native_enum=False, length=16), nullable=False
    )
    validation_outcome: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class TaskDefinition(Base):
    __tablename__ = "task_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "course_id", "key", name="uq_task_definition_key"),
        CheckConstraint("version >= 1", name="ck_task_definition_version_positive"),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    course_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    node_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class TaskVersion(Base):
    __tablename__ = "task_versions"
    __table_args__ = (
        UniqueConstraint("definition_id", "version", name="uq_task_version_number"),
        UniqueConstraint("definition_id", "snapshot_digest", name="uq_task_version_digest"),
        CheckConstraint("version >= 1", name="ck_task_version_positive"),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    definition_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("task_definitions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    snapshot_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created_at()


class TaskInstance(Base):
    __tablename__ = "task_instances"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_task_instance_version_positive"),
        Index(
            "uq_task_instance_active",
            "student_id",
            "task_version_id",
            "active_key",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("task_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    active_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[TaskInstanceStatus] = mapped_column(
        SqlEnum(TaskInstanceStatus, native_enum=False, length=16),
        default=TaskInstanceStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    snapshot_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    started_at: Mapped[datetime] = _created_at()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = _updated_at()


class TaskStatusHistory(Base):
    __tablename__ = "task_status_history"

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    task_instance_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("task_instances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[TaskInstanceStatus | None] = mapped_column(
        SqlEnum(TaskInstanceStatus, native_enum=False, length=16), nullable=True
    )
    to_status: Mapped[TaskInstanceStatus] = mapped_column(
        SqlEnum(TaskInstanceStatus, native_enum=False, length=16), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = _created_at()


class AssessmentResult(Base):
    __tablename__ = "assessment_results"
    __table_args__ = (
        UniqueConstraint("evidence_event_id", name="uq_assessment_evidence_event"),
        CheckConstraint("hints_used >= 0", name="ck_assessment_hints_nonnegative"),
        CheckConstraint(
            "support_level >= 0 AND support_level <= 3",
            name="ck_assessment_support_level_range",
        ),
        CheckConstraint(
            "independence_score >= 0.0 AND independence_score <= 1.0",
            name="ck_assessment_independence_range",
        ),
        CheckConstraint(
            "transfer_score >= 0.0 AND transfer_score <= 1.0",
            name="ck_assessment_transfer_range",
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    node_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    task_instance_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("task_instances.id", ondelete="SET NULL"), nullable=True, index=True
    )
    evidence_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    hidden_tests_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    hints_used: Mapped[int] = mapped_column(nullable=False)
    support_level: Mapped[int] = mapped_column(nullable=False)
    independence_score: Mapped[float] = mapped_column(Float, nullable=False)
    transfer_score: Mapped[float] = mapped_column(Float, nullable=False)
    platform_error: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class MasteryState(Base):
    __tablename__ = "mastery_states"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "course_id",
            "node_id",
            name="uq_mastery_student_course_node",
        ),
        CheckConstraint("version >= 1", name="ck_mastery_state_version_positive"),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    node_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    status: Mapped[MasteryStatus] = mapped_column(
        SqlEnum(MasteryStatus, native_enum=False, length=32),
        default=MasteryStatus.UNSEEN,
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    last_evidence_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    initial_mastery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stable_mastery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class MasteryStateHistory(Base):
    __tablename__ = "mastery_state_history"

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    mastery_state_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mastery_states.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[MasteryStatus | None] = mapped_column(
        SqlEnum(MasteryStatus, native_enum=False, length=32), nullable=True
    )
    to_status: Mapped[MasteryStatus] = mapped_column(
        SqlEnum(MasteryStatus, native_enum=False, length=32), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = _created_at()


class ReviewSchedule(Base):
    __tablename__ = "review_schedules"
    __table_args__ = (
        CheckConstraint("hint_ceiling >= 0", name="ck_review_hint_ceiling_nonnegative"),
        CheckConstraint("reschedule_count >= 0", name="ck_review_reschedule_count_nonnegative"),
        CheckConstraint("version >= 1", name="ck_review_schedule_version_positive"),
        Index(
            "uq_review_schedule_active",
            "student_id",
            "course_id",
            "node_id",
            unique=True,
            postgresql_where=text("status IN ('SCHEDULED', 'DUE')"),
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    node_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    mastery_state_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mastery_states.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scenario_key: Mapped[str] = mapped_column(String(128), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    original_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hint_ceiling: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        SqlEnum(ReviewStatus, native_enum=False, length=16),
        default=ReviewStatus.SCHEDULED,
        nullable=False,
        index=True,
    )
    reschedule_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_rescheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class ReviewAttempt(Base):
    __tablename__ = "review_attempts"
    __table_args__ = (
        UniqueConstraint("evidence_event_id", name="uq_review_attempt_evidence_event"),
        CheckConstraint("hints_used >= 0", name="ck_review_attempt_hints_nonnegative"),
        CheckConstraint(
            "support_level >= 0 AND support_level <= 3",
            name="ck_review_attempt_support_level_range",
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    review_schedule_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("review_schedules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assessment_result_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("assessment_results.id", ondelete="SET NULL"), nullable=True
    )
    evidence_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[ReviewAttemptOutcome] = mapped_column(
        SqlEnum(ReviewAttemptOutcome, native_enum=False, length=16), nullable=False
    )
    scenario_key: Mapped[str] = mapped_column(String(128), nullable=False)
    hints_used: Mapped[int] = mapped_column(nullable=False)
    support_level: Mapped[int] = mapped_column(nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()
