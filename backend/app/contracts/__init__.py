"""Shared, versioned wire contracts (Pydantic mirror of @pymentor/contracts).

This package is the Python side of the frozen Pydantic ↔ Zod boundary. Every
model here MUST stay field-identical to its Zod twin in
``packages/contracts/src/``. The conformance gate
``backend/tests/test_contracts_parity.py`` enforces it.
"""

from app.contracts.auth import (
    AuthTokens,
    LoginRequest,
    PendingRegistration,
    RegisterRequest,
    RegisterResponse,
    RegistrationDecisionRequest,
    TokenRefreshRequest,
    UserProfile,
)
from app.contracts.consistency import (
    AuditEvent,
    EvidenceEvent,
    EvidenceEventType,
    IdempotencyRecord,
    OutboxEventModel,
)
from app.contracts.errors import ErrorCode, ErrorEnvelope, FieldError
from app.contracts.health import HealthResponse, HealthStatus, SystemPingResponse
from app.contracts.learning import (
    AssessmentSubmission,
    LearningPathStatusContract,
    MasteryStatusContract,
    MasteryView,
    PathSnapshot,
    PathStepKindContract,
    PathStepView,
    PathValidationStatusContract,
    ProfileDimensionContract,
    ProfileDimensionView,
    ProfileDisputeRequest,
    ProfileSnapshot,
    ReviewRescheduleRequest,
    ReviewStatusContract,
    ReviewView,
    TaskInstanceStatusContract,
    TaskStartResponse,
    TodayItem,
)
from app.contracts.sandbox import (
    SandboxResult,
    SandboxRunStatus,
    SandboxTestCaseResult,
    TraceFrame,
)
from app.contracts.streaming import (
    ChatCompletionChunk,
    ContentDeltaEvent,
    DoneEvent,
    ProgressEvent,
    ReasoningDeltaEvent,
    StreamErrorEvent,
    StreamEvent,
    StreamEventType,
    StreamInlineError,
    ToolCallDelta,
    ToolCallDeltaEvent,
)
from app.contracts.worker import (
    WorkerJobEnvelope,
    WorkerJobKind,
    WorkerJobStatus,
)

__all__ = [
    "AssessmentSubmission",
    "AuditEvent",
    "AuthTokens",
    "ChatCompletionChunk",
    "ContentDeltaEvent",
    "DoneEvent",
    "ErrorCode",
    "ErrorEnvelope",
    "EvidenceEvent",
    "EvidenceEventType",
    "FieldError",
    "HealthResponse",
    "HealthStatus",
    "IdempotencyRecord",
    "LearningPathStatusContract",
    "LoginRequest",
    "MasteryStatusContract",
    "MasteryView",
    "OutboxEventModel",
    "PathSnapshot",
    "PathStepKindContract",
    "PathStepView",
    "PathValidationStatusContract",
    "PendingRegistration",
    "ProfileDimensionContract",
    "ProfileDimensionView",
    "ProfileDisputeRequest",
    "ProfileSnapshot",
    "ProgressEvent",
    "ReasoningDeltaEvent",
    "RegisterRequest",
    "RegisterResponse",
    "RegistrationDecisionRequest",
    "ReviewRescheduleRequest",
    "ReviewStatusContract",
    "ReviewView",
    "SandboxResult",
    "SandboxRunStatus",
    "SandboxTestCaseResult",
    "StreamErrorEvent",
    "StreamEvent",
    "StreamEventType",
    "StreamInlineError",
    "SystemPingResponse",
    "TaskInstanceStatusContract",
    "TaskStartResponse",
    "TodayItem",
    "TokenRefreshRequest",
    "ToolCallDelta",
    "ToolCallDeltaEvent",
    "TraceFrame",
    "UserProfile",
    "WorkerJobEnvelope",
    "WorkerJobKind",
    "WorkerJobStatus",
]
