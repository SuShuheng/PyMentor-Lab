"""Wire contracts for the deterministic learning loop (BE-004).

Mirror of ``packages/contracts/src/learning.ts``. Formal decisions are
returned as versioned views; the assessment submission carries only the
accepted evidence identifier rather than client-asserted correctness facts.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProfileDimensionContract(StrEnum):
    CONCEPT_KNOWLEDGE = "CONCEPT_KNOWLEDGE"
    EXECUTION_MODEL = "EXECUTION_MODEL"
    IMPLEMENTATION = "IMPLEMENTATION"
    DECOMPOSITION = "DECOMPOSITION"
    DEBUGGING = "DEBUGGING"
    TESTING = "TESTING"
    TRANSFER = "TRANSFER"
    INDEPENDENCE_SUPPORT = "INDEPENDENCE_SUPPORT"


class LearningPathStatusContract(StrEnum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class PathStepKindContract(StrEnum):
    REVIEW = "REVIEW"
    LEARN = "LEARN"
    PRACTICE = "PRACTICE"
    ASSESSMENT = "ASSESSMENT"


class PathValidationStatusContract(StrEnum):
    VALIDATED = "VALIDATED"
    REPAIRED = "REPAIRED"
    FALLBACK = "FALLBACK"


class TaskInstanceStatusContract(StrEnum):
    ACTIVE = "ACTIVE"
    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MasteryStatusContract(StrEnum):
    UNSEEN = "UNSEEN"
    LEARNING = "LEARNING"
    PASSED_WITH_HELP = "PASSED_WITH_HELP"
    INITIAL_MASTERY = "INITIAL_MASTERY"
    STABLE_MASTERY = "STABLE_MASTERY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ReviewStatusContract(StrEnum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProfileDimensionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: ProfileDimensionContract
    scope_key: str = Field(min_length=1, max_length=128)
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    support_level: int = Field(ge=0, le=3)


class ProfileSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    student_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    source_event_id: str = Field(min_length=1)
    dimensions: list[ProfileDimensionView]


class ProfileDisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_version_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2000)


class ProfileDisputeView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    profile_version_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2000)


class OnboardingAnswers(BaseModel):
    """Self-reported onboarding answers (BE-018).

    These are recorded as evidence and feed the deterministic profile
    projection with low confidence; they never auto-advance mastery
    (CONTRACT rule). Field names mirror the V1.0 frontend onboarding flow.
    """

    model_config = ConfigDict(extra="forbid")

    prior_experience: str = Field(min_length=1, max_length=128)
    primary_goal: str = Field(min_length=1, max_length=128)
    error_strategy: str = Field(min_length=1, max_length=128)
    preferred_exercise: str = Field(min_length=1, max_length=128)
    weekly_band: str = Field(min_length=1, max_length=64)


class OnboardingSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: OnboardingAnswers
    expected_profile_version: int = Field(ge=0)


class OnboardingSubmissionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_event_id: str = Field(min_length=1, max_length=128)
    profile_version_id: str = Field(min_length=1)
    profile_version: int = Field(ge=1)
    replan_requested: bool
    # BE-018 fix: true once a synchronous first LearningPath has been compiled
    # for this student/course. False means the course had no nodes to seed
    # (student will see an empty state until the catalogue is populated) or a
    # CURRENT path already existed before onboarding and was left untouched.
    path_compiled: bool = False


class PathStepView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    position: int = Field(ge=1)
    node_id: str = Field(min_length=1)
    kind: PathStepKindContract
    estimated_minutes: int = Field(ge=1)
    scenario_key: str = Field(min_length=1, max_length=128)
    validation_status: PathValidationStatusContract


class PathSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    status: LearningPathStatusContract
    steps: list[PathStepView]


class TodayItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    kind: PathStepKindContract
    estimated_minutes: int = Field(ge=1)
    due_at: str | None = None
    task_version_id: str | None = None


class TaskStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    task_version_id: str = Field(min_length=1)
    status: TaskInstanceStatusContract
    snapshot: dict[str, Any]
    started_at: str = Field(min_length=1)
    version: int = Field(ge=1)


class AssessmentSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_event_id: str = Field(min_length=1, max_length=128)
    expected_task_version: int = Field(ge=1)


class TaskSubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(min_length=1)
    task_instance_id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    status: MasteryStatusContract | Literal["PLATFORM_ERROR"]
    version: int = Field(ge=0)
    review_due_at: str | None = None


class MasteryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    status: MasteryStatusContract
    version: int = Field(ge=1)
    review_due_at: str | None = None


class ReviewView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    scenario_key: str = Field(min_length=1, max_length=128)
    due_at: str = Field(min_length=1)
    status: ReviewStatusContract
    reschedule_count: int = Field(ge=0)
    version: int = Field(ge=1)


class ReviewRescheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    due_at: str = Field(min_length=1)
    expected_version: int = Field(ge=1)
