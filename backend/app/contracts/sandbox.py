"""Versioned code-run and sandbox-supervisor wire contracts.

Mirror of ``packages/contracts/src/sandbox.ts``. Hidden tests and full hint
content use these types only on trusted backend/supervisor boundaries.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CodeRunMode(StrEnum):
    RUN = "RUN"
    TRACE = "TRACE"
    SUBMIT = "SUBMIT"


class CodeRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    USER_ERROR = "USER_ERROR"
    PLATFORM_ERROR = "PLATFORM_ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class SandboxRunStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class TestVisibility(StrEnum):
    VISIBLE = "VISIBLE"
    HIDDEN = "HIDDEN"


class SandboxComparison(StrEnum):
    EQUAL = "EQUAL"
    APPROX = "APPROX"
    UNORDERED = "UNORDERED"
    MATCHES = "MATCHES"


class SandboxEntrypointKind(StrEnum):
    FUNCTION = "FUNCTION"
    SCRIPT = "SCRIPT"


class SandboxPhase(StrEnum):
    VISIBLE = "VISIBLE"
    HIDDEN = "HIDDEN"


class SandboxEntrypoint(StrictContract):
    kind: SandboxEntrypointKind
    name: str | None = Field(default=None, min_length=1, max_length=128)


class SandboxTestCase(StrictContract):
    id: str = Field(min_length=1, max_length=128)
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    expected: Any = None
    stdin: str | None = Field(default=None, max_length=65_536)
    expected_stdout: str | None = Field(default=None, max_length=65_536)
    comparison: SandboxComparison = SandboxComparison.EQUAL
    transfer: bool = False


class SandboxTaskTests(StrictContract):
    entrypoint: SandboxEntrypoint
    allowed_imports: list[str] = Field(default_factory=list, max_length=32)
    visible: list[SandboxTestCase] = Field(default_factory=list, max_length=256)
    hidden: list[SandboxTestCase] = Field(default_factory=list, max_length=256)


class SandboxHint(StrictContract):
    key: str = Field(min_length=1, max_length=128)
    level: int = Field(ge=1, le=3)
    content: str = Field(min_length=1, max_length=8_192)
    independence_cost: float = Field(ge=0, le=100)


class SandboxHintPolicy(StrictContract):
    max_level: int = Field(ge=0, le=3)
    hints: list[SandboxHint] = Field(default_factory=list, max_length=3)


class SandboxExecutionPolicy(StrictContract):
    timeout_ms: int = Field(ge=100, le=30_000)
    memory_mb: int = Field(ge=16, le=1_024)
    pids_limit: int = Field(ge=1, le=128)
    output_limit_bytes: int = Field(ge=1_024, le=1_048_576)
    test_limit: int = Field(ge=1, le=256)
    trace_frame_limit: int = Field(ge=1, le=1_000)


class SandboxTestCaseResult(StrictContract):
    case_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    visibility: TestVisibility
    comparison: SandboxComparison
    transfer: bool
    passed: bool
    message: str | None = None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    duration_ms: int = Field(ge=0)


class TraceFrame(StrictContract):
    """A deterministic code-trace frame emitted by AST instrumentation."""

    sequence: int = Field(ge=1)
    line: int = Field(gt=0)
    event: Literal["call", "line", "return", "exception"]
    func_name: str = Field(min_length=1, max_length=256)
    locals: dict[str, str] | None = None


class SandboxResourceUsage(StrictContract):
    cpu_ms: int = Field(ge=0)
    wall_ms: int = Field(ge=0)
    peak_memory_kb: int | None = Field(default=None, ge=0)
    exit_code: int | None = None


class SandboxResult(StrictContract):
    """A bounded result; platform errors remain separate from user errors."""

    run_id: str = Field(min_length=1)
    status: SandboxRunStatus
    passed: bool
    stdout: str
    stderr: str
    tests: list[SandboxTestCaseResult] = Field(max_length=256)
    trace_frames: list[TraceFrame] | None = Field(default=None, max_length=1_000)
    resource_usage: SandboxResourceUsage
    stdout_truncated: bool
    stderr_truncated: bool
    trace_truncated: bool
    user_error: str | None = None
    platform_error: str | None = None


class SandboxExecutionRequest(StrictContract):
    protocol_version: Literal["1"]
    request_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    source_code: str = Field(min_length=1, max_length=65_536)
    entrypoint: SandboxEntrypoint
    cases: list[SandboxTestCase] = Field(max_length=256)
    allowed_imports: list[str] = Field(max_length=32)
    phase: SandboxPhase
    policy: SandboxExecutionPolicy
    trace_enabled: bool


class SandboxExecutionResponse(StrictContract):
    protocol_version: Literal["1"]
    request_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    result: SandboxResult


class CodeRunRequest(StrictContract):
    task_instance_id: str = Field(min_length=1)
    source_code: str = Field(min_length=1, max_length=65_536)
    mode: Literal[CodeRunMode.RUN, CodeRunMode.TRACE]
    expected_task_version: int = Field(ge=1)
    trace_enabled: bool = False


class CodeSubmissionRequest(StrictContract):
    task_instance_id: str = Field(min_length=1)
    source_code: str = Field(min_length=1, max_length=65_536)
    expected_task_version: int = Field(ge=1)


class CodeRevisionView(StrictContract):
    id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    source_digest: str = Field(min_length=64, max_length=64)
    created_at: datetime


class CodeRunView(StrictContract):
    run_id: str = Field(min_length=1)
    task_instance_id: str = Field(min_length=1)
    mode: CodeRunMode
    status: CodeRunStatus
    version: int = Field(ge=1)
    revision: CodeRevisionView
    result: SandboxResult | None = None
    evidence_event_id: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class HintRequest(StrictContract):
    level: int = Field(ge=1, le=3)
    revision_id: str | None = Field(default=None, min_length=1)
    expected_task_version: int = Field(ge=1)


class HintUsageView(StrictContract):
    id: str = Field(min_length=1)
    task_instance_id: str = Field(min_length=1)
    revision_id: str | None = Field(default=None, min_length=1)
    sequence: int = Field(ge=1)
    hint_key: str = Field(min_length=1, max_length=128)
    level: int = Field(ge=1, le=3)
    cost: float = Field(ge=0)
    content: str = Field(min_length=1, max_length=8_192)
    created_at: datetime
