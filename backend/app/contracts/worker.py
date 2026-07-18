"""Versioned FastAPI ↔ Agent Worker contract mirrors.

Mirror of :mod:`packages/contracts/src/worker.ts`. The Worker emits proposals,
progress, and redacted audit only; FastAPI owns formal learning state.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SafeId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    ),
]
SafeCode = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]{0,63}$"),
]
Sha256Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Summary = Annotated[str, Field(min_length=1, max_length=8_000)]
ShortText = Annotated[str, Field(min_length=1, max_length=1_000)]
StrictInteger = Annotated[int, Field(strict=True)]
StrictNumber = Annotated[float, Field(strict=True)]
StrictBoolean = Annotated[bool, Field(strict=True)]
UnitScore = Annotated[StrictNumber, Field(ge=0, le=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkerJobKind(StrEnum):
    PROFILE_DIAGNOSE = "profile_diagnose"
    PATH_RECOMMEND = "path_recommend"
    RESOURCE_GENERATE = "resource_generate"
    CODING_COACH = "coding_coach"
    ASSESSMENT_FEEDBACK = "assessment_feedback"
    TUTORING_ANSWER = "tutoring_answer"


class WorkerJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    CANCELLED = "CANCELLED"


class AgentNodeName(StrEnum):
    ORCHESTRATOR = "orchestrator"
    PROFILE = "profile"
    PATH = "path"
    RESOURCE = "resource"
    COACH = "coach"
    ASSESSMENT = "assessment"


class SpecialistAgentNodeName(StrEnum):
    PROFILE = "profile"
    PATH = "path"
    RESOURCE = "resource"
    COACH = "coach"
    ASSESSMENT = "assessment"


class AgentContext(StrictModel):
    course_id: SafeId | None = None
    node_id: SafeId | None = None
    task_id: SafeId | None = None
    evidence_event_ids: list[SafeId] = Field(max_length=64)


class OrchestratorAgentInput(StrictModel):
    kind: WorkerJobKind
    request: str = Field(min_length=1, max_length=4_000)
    context: AgentContext


class OrchestratorAgentOutput(StrictModel):
    route: SpecialistAgentNodeName
    intent_code: SafeCode
    summary: ShortText


class ProfileAgentInput(StrictModel):
    evidence_summary: Summary
    current_profile_version: StrictInteger = Field(gt=0)
    context: AgentContext


class ProfileChange(StrictModel):
    dimension: SafeCode
    delta: StrictNumber = Field(ge=-1, le=1)
    reason: ShortText


class ProfileAgentOutput(StrictModel):
    kind: Literal["profile_change"]
    changes: list[ProfileChange] = Field(min_length=1, max_length=16)


class PathAgentInput(StrictModel):
    profile_summary: Summary
    available_minutes: StrictInteger = Field(ge=1, le=1_440)
    candidate_node_ids: list[SafeId] = Field(min_length=1, max_length=64)
    context: AgentContext


class PathStepProposal(StrictModel):
    node_id: SafeId
    action: Literal["LEARN", "REMEDIATE", "REVIEW", "PRACTICE"]
    reason: ShortText


class PathAgentOutput(StrictModel):
    kind: Literal["path_plan"]
    steps: list[PathStepProposal] = Field(min_length=1, max_length=32)


class LearningResourceType(StrEnum):
    MICRO_LECTURE = "MICRO_LECTURE"
    STRUCTURE_CARD = "STRUCTURE_CARD"
    TRACE_ANIMATION = "TRACE_ANIMATION"
    LAYERED_EXERCISE = "LAYERED_EXERCISE"
    NOTEBOOK_TASK = "NOTEBOOK_TASK"


class ResourceAgentInput(StrictModel):
    learning_need: Summary
    resource_types: list[LearningResourceType] = Field(min_length=1, max_length=5)
    tutoring_question: str | None = Field(default=None, min_length=1, max_length=4_000)
    context: AgentContext


class ResourceRequest(StrictModel):
    resource_type: LearningResourceType
    objective: ShortText


class ResourceAgentOutput(StrictModel):
    kind: Literal["resource_request"]
    requests: list[ResourceRequest] = Field(min_length=1, max_length=5)
    answer: str | None = Field(default=None, min_length=1, max_length=8_000)


class CoachAgentInput(StrictModel):
    error_summary: Summary
    test_summary: Summary
    hint_level: StrictInteger = Field(ge=1, le=3)
    context: AgentContext


class CoachAgentOutput(StrictModel):
    kind: Literal["coaching_feedback"]
    diagnosis: Summary
    hints: list[ShortText] = Field(min_length=1, max_length=3)
    next_test: ShortText


class AssessmentAgentInput(StrictModel):
    response_summary: Summary
    rubric_keys: list[SafeCode] = Field(min_length=1, max_length=16)
    context: AgentContext


class AssessmentAgentOutput(StrictModel):
    kind: Literal["assessment_feedback"]
    rubric_scores: dict[SafeCode, UnitScore]
    feedback: Summary
    evidence_claims: list[ShortText] = Field(max_length=16)


AgentProposal = Annotated[
    ProfileAgentOutput
    | PathAgentOutput
    | ResourceAgentOutput
    | CoachAgentOutput
    | AssessmentAgentOutput,
    Field(discriminator="kind"),
]


class WorkerJobEnvelope(StrictModel):
    """Versioned envelope: idempotent by event_id, replay-safe, traceable."""

    schema_version: Literal[1] = 1
    event_id: SafeId
    trace_id: SafeId
    tenant_id: SafeId
    student_id: SafeId
    kind: WorkerJobKind
    payload: dict[Annotated[str, Field(max_length=64)], object] = Field(default_factory=dict)
    enqueued_at: AwareDatetime


class AgentProposalEnvelope(StrictModel):
    schema_version: Literal[1] = 1
    agent_run_id: SafeId
    event_id: SafeId
    trace_id: SafeId
    tenant_id: SafeId
    student_id: SafeId
    node: SpecialistAgentNodeName
    status: Literal["SUCCEEDED", "FAILED_RETRYABLE", "FAILED_FINAL"]
    proposal: AgentProposal | None
    error_code: SafeCode | None = None
    fallback_used: StrictBoolean
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> AgentProposalEnvelope:
        if self.status == "SUCCEEDED" and self.proposal is None:
            raise ValueError("successful Agent run requires a proposal")
        if self.status == "SUCCEEDED":
            if self.error_code is not None:
                raise ValueError("successful Agent run cannot include an error code")
            expected_kind = {
                SpecialistAgentNodeName.PROFILE: "profile_change",
                SpecialistAgentNodeName.PATH: "path_plan",
                SpecialistAgentNodeName.RESOURCE: "resource_request",
                SpecialistAgentNodeName.COACH: "coaching_feedback",
                SpecialistAgentNodeName.ASSESSMENT: "assessment_feedback",
            }[self.node]
            if self.proposal is not None and self.proposal.kind != expected_kind:
                raise ValueError("proposal kind does not match producing Agent node")
        else:
            if self.proposal is not None:
                raise ValueError("failed Agent run cannot include a proposal")
            if self.error_code is None:
                raise ValueError("failed Agent run requires an error code")
        return self


class AgentAuditEventType(StrEnum):
    RUN_STARTED = "RUN_STARTED"
    NODE_STARTED = "NODE_STARTED"
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    TOOL_FAILED = "TOOL_FAILED"
    NODE_COMPLETED = "NODE_COMPLETED"
    NODE_FAILED = "NODE_FAILED"
    CHECKPOINT_SAVED = "CHECKPOINT_SAVED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED = "RUN_FAILED"
    RUN_CANCELLED = "RUN_CANCELLED"
    REPLAY_STARTED = "REPLAY_STARTED"


class AgentAuditDetail(StrictModel):
    status: WorkerJobStatus | None = None
    code: SafeCode | None = None
    latency_ms: StrictInteger | None = Field(default=None, ge=0, le=3_600_000)
    input_bytes: StrictInteger | None = Field(default=None, ge=0, le=1_048_576)
    output_bytes: StrictInteger | None = Field(default=None, ge=0, le=1_048_576)
    argument_digest: Sha256Digest | None = None
    result_digest: Sha256Digest | None = None
    retry_count: StrictInteger | None = Field(default=None, ge=0, le=10)
    fallback: StrictBoolean | None = None


class AgentAuditEnvelope(StrictModel):
    schema_version: Literal[1] = 1
    agent_run_id: SafeId
    event_id: SafeId
    trace_id: SafeId
    tenant_id: SafeId
    student_id: SafeId
    sequence: StrictInteger = Field(gt=0, le=1_000_000)
    event_type: AgentAuditEventType
    node: AgentNodeName | None = None
    tool_name: SafeId | None = None
    checkpoint_id: SafeId | None = None
    detail: AgentAuditDetail
    occurred_at: AwareDatetime


class AgentReplayRequest(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: SafeId
    original_event_id: SafeId
    replay_event_id: SafeId
    checkpoint_id: SafeId
    requested_at: AwareDatetime

    @model_validator(mode="after")
    def distinct_replay_identity(self) -> AgentReplayRequest:
        if self.original_event_id == self.replay_event_id:
            raise ValueError("replay event identity must differ from the original")
        return self
