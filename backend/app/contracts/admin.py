"""Strict renderer-facing contracts for BE-010 administrative read APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictAdminModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageMetadata(StrictAdminModel):
    number: int = Field(ge=1)
    size: int = Field(ge=1, le=100)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class AdminStudentSummary(StrictAdminModel):
    id: UUID
    email: str = Field(min_length=3, max_length=255)
    student_no: str | None = Field(max_length=64)
    display_name: str | None = Field(max_length=128)
    status: str = Field(min_length=1, max_length=32)
    created_at: datetime
    profile_version: int = Field(ge=0)
    completed_tasks: int = Field(ge=0)
    due_reviews: int = Field(ge=0)


class AdminStudentPage(StrictAdminModel):
    items: list[AdminStudentSummary]
    page: PageMetadata


class AdminProfileDimension(StrictAdminModel):
    dimension: str = Field(min_length=1, max_length=32)
    scope_key: str = Field(min_length=1, max_length=128)
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    support_level: int = Field(ge=0, le=3)


class AdminStudentProfile(StrictAdminModel):
    student_id: UUID
    version: int = Field(ge=0)
    dimensions: list[AdminProfileDimension]
    created_at: datetime | None


class AdminStudentProgress(StrictAdminModel):
    student_id: UUID
    current_path_id: UUID | None
    current_node_id: UUID | None
    completed_tasks: int = Field(ge=0)
    due_reviews: int = Field(ge=0)
    mastery_counts: dict[str, int]
    last_active_at: datetime | None


class AdminEvidenceItem(StrictAdminModel):
    id: UUID
    event_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=64)
    course_id: UUID | None
    node_id: UUID | None
    task_id: UUID | None
    trace_id: str = Field(min_length=1, max_length=128)
    evidence_confidence: float = Field(ge=0, le=1)
    created_at: datetime


class AdminEvidencePage(StrictAdminModel):
    items: list[AdminEvidenceItem]
    page: PageMetadata


class AdminMasterySummary(StrictAdminModel):
    course_id: UUID | None
    total_states: int = Field(ge=0)
    counts: dict[str, int]
    due_reviews: int = Field(ge=0)
    stable_ratio: float = Field(ge=0, le=1)


class AdminResourceGateReview(StrictAdminModel):
    gate: str = Field(min_length=1, max_length=16)
    version: int = Field(ge=1)
    passed: bool
    findings: list[str]
    reviewer: str = Field(min_length=1, max_length=128)
    created_at: datetime


class AdminResourceReviewItem(StrictAdminModel):
    resource_id: UUID
    job_id: UUID
    student_id: UUID
    resource_type: str = Field(min_length=1, max_length=32)
    version: int = Field(ge=1)
    status: str = Field(min_length=1, max_length=32)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    gates: list[AdminResourceGateReview]


class AdminResourceReviewPage(StrictAdminModel):
    items: list[AdminResourceReviewItem]
    page: PageMetadata


class AdminAgentToolCall(StrictAdminModel):
    sequence: int = Field(ge=1)
    node: str | None = Field(max_length=32)
    tool_name: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=32)
    status: str | None = Field(max_length=32)
    argument_digest: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    result_digest: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    latency_ms: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    error_code: str | None = Field(max_length=64)
    occurred_at: datetime


class AdminOverview(StrictAdminModel):
    """Live tenant-scoped aggregate counts for the admin overview dashboard.

    Each field is scoped to the requesting administrator's tenant; the
    legacy V1.0 frontend hardcoded these values (e.g. ``active_students=248``,
    ``resource_reviews=7``), so the renderer depends on every count being
    non-negative and never leaking across tenants.
    """

    active_students: int = Field(ge=0)
    pending_registrations: int = Field(ge=0)
    resource_reviews: int = Field(ge=0)
    due_reviews: int = Field(ge=0)


class AdminAgentRunView(StrictAdminModel):
    external_run_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    student_id: UUID
    status: str = Field(min_length=1, max_length=32)
    route: str | None = Field(max_length=32)
    latest_sequence: int = Field(ge=0)
    checkpoint_thread_id: str | None = Field(max_length=128)
    latest_checkpoint_id: str | None = Field(max_length=128)
    fallback_used: bool
    error_code: str | None = Field(max_length=64)
    input_snapshot: dict[str, Any]
    output_snapshot: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    tool_calls: list[AdminAgentToolCall]
