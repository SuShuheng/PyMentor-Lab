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


class AdminMetricsWindow(StrictAdminModel):
    """Resolved query window reported back to the renderer.

    ``bucket`` is the chosen granularity (``hour`` for windows up to 36h,
    ``day`` otherwise) and ``bucket_count`` is the number of discrete buckets
    spanning ``[since, until)`` so FE-025 can pre-size chart axes.
    """

    since: datetime
    until: datetime
    bucket: str = Field(min_length=1, max_length=8)
    bucket_count: int = Field(ge=1)


class AdminApiUsageBucket(StrictAdminModel):
    """One time bucket of Provider call volume / latency / error aggregates.

    Percentiles are ``None`` when the bucket recorded no calls so the chart can
    render a gap instead of a misleading zero.
    """

    bucket_start: datetime
    calls: int = Field(ge=0)
    p50_latency_ms: int | None = Field(default=None, ge=0)
    p95_latency_ms: int | None = Field(default=None, ge=0)
    error_rate: float = Field(ge=0, le=1)
    throttle_rate: float = Field(ge=0, le=1)


class AdminApiUsageSeries(StrictAdminModel):
    buckets: list[AdminApiUsageBucket]


class AdminMasteryDistribution(StrictAdminModel):
    """Tenant-scoped MasteryState counts keyed by MasteryStatus value.

    Every status enum value is materialized with a zero count when absent so
    FE-025 can render a stable distribution regardless of tenant activity.
    """

    course_id: UUID | None
    node_id: UUID | None
    total_states: int = Field(ge=0)
    counts: dict[str, int]


class AdminAgentTimelinePoint(StrictAdminModel):
    """One time bucket of AgentRun volume broken down by outcome.

    ``fallback_used`` counts runs whose safety fallback engaged; ``failed``
    counts runs whose terminal status was not SUCCEEDED.
    """

    bucket_start: datetime
    total: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    fallback_used: int = Field(ge=0)


class AdminAgentTimeline(StrictAdminModel):
    buckets: list[AdminAgentTimelinePoint]


class AdminResourceTypeStat(StrictAdminModel):
    """Per-resource-type counts, publication success rate, and generation time.

    ``success_rate`` is ``PUBLISHED / total`` (0 when no resources of the type
    exist). ``avg_generation_ms`` is the mean wall time between resource
    ``created_at`` and ``updated_at`` and is ``None`` when no resources of the
    type exist in the window.
    """

    resource_type: str = Field(min_length=1, max_length=32)
    total: int = Field(ge=0)
    staged: int = Field(ge=0)
    reviewing: int = Field(ge=0)
    published: int = Field(ge=0)
    rejected: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=1)
    avg_generation_ms: float | None = Field(default=None, ge=0)


class AdminResourceStats(StrictAdminModel):
    items: list[AdminResourceTypeStat]


class AdminMetricsAggregate(StrictAdminModel):
    """BE-028 advanced metrics aggregate powering FE-025 charts and FE-026 stats.

    ``api_usage`` and ``agent_timeline`` are tenant-wide operational signals
    (neither ProviderCallRecord nor AgentRun carry a node_id), while
    ``mastery_distribution`` and ``resource_stats`` honour the optional
    ``node_id`` / ``course_id`` filters. Every series is tenant-scoped.
    """

    window: AdminMetricsWindow
    api_usage: AdminApiUsageSeries
    mastery_distribution: AdminMasteryDistribution
    agent_timeline: AdminAgentTimeline
    resource_stats: AdminResourceStats


# --- BE-020 Agent prompt template tuning -------------------------------------
# The six LangGraph node names externalized from
# workers/agent-worker/src/agents/nodes.ts. Kept as a literal tuple so the
# contracts module stays dependency-free.
AGENT_PROMPT_NODES: tuple[str, ...] = (
    "orchestrator",
    "profile",
    "path",
    "resource",
    "coach",
    "assessment",
)


class AgentPromptTemplateView(StrictAdminModel):
    id: UUID
    node: str = Field(min_length=1, max_length=32)
    version: int = Field(ge=1)
    system_prompt: str = Field(min_length=1)
    published: bool
    created_by: UUID | None
    created_at: datetime


class AgentPromptTemplateCreate(StrictAdminModel):
    system_prompt: str = Field(min_length=1, max_length=32_000)


class AgentPromptTemplateHistoryPage(StrictAdminModel):
    items: list[AgentPromptTemplateView]
    page: PageMetadata


class AgentPromptDryRunRequest(StrictAdminModel):
    system_prompt: str = Field(min_length=1, max_length=32_000)
    sample_input: dict[str, Any] = Field(default_factory=dict)


class AgentPromptDryRunView(StrictAdminModel):
    """Result of executing a candidate prompt against a sandbox case.

    For V1.1 the Worker runtime integration is intentionally stubbed: the API
    contract is what the renderer depends on, and ``implemented=False`` plus the
    explicit ``note`` keep the stub honest. The Worker fetches the published
    prompt via ``GET /api/v1/admin/agent-prompts/{node}`` at runtime.
    """

    node: str = Field(min_length=1, max_length=32)
    implemented: bool
    note: str = Field(min_length=1, max_length=256)
