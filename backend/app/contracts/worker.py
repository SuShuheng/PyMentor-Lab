"""Worker job envelope contract (Pydantic mirror).

Mirror of ``packages/contracts/src/worker.ts``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class WorkerJobEnvelope(BaseModel):
    """Versioned envelope: idempotent by event_id, replay-safe, traceable."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    event_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    student_id: str = Field(min_length=1)
    kind: WorkerJobKind
    payload: dict[str, object] = Field(default_factory=dict)
    enqueued_at: str = Field(min_length=1)
