"""Sandbox result contract (Pydantic mirror).

Mirror of ``packages/contracts/src/sandbox.ts``. The platform_error vs
user_error split is critical: platform failures never reduce mastery.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SandboxRunStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class SandboxTestCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    passed: bool
    message: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    duration_ms: int = Field(ge=0)


class TraceFrame(BaseModel):
    """A deterministic code-trace frame emitted by AST instrumentation."""

    model_config = ConfigDict(extra="forbid")

    line: int = Field(gt=0)
    event: str  # "call" | "line" | "return" | "exception"
    func_name: str = Field(min_length=1)
    locals: dict[str, str] | None = None


class SandboxResult(BaseModel):
    """The bounded sandbox result. All fields are size-capped by the runner."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    status: SandboxRunStatus
    passed: bool
    stdout: str
    stderr: str
    tests: list[SandboxTestCaseResult]
    trace: list[TraceFrame] | None = None
    duration_ms: int = Field(ge=0)
    peak_memory_kb: int | None = Field(default=None, ge=0)
    user_error: str | None = None
    platform_error: str | None = None
