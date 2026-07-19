"""Tenant-scoped read models for BE-010 administrative visibility."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.contracts.admin import (
    AdminAgentRunView,
    AdminAgentTimeline,
    AdminAgentTimelinePoint,
    AdminAgentToolCall,
    AdminApiUsageBucket,
    AdminApiUsageSeries,
    AdminEvidenceItem,
    AdminEvidencePage,
    AdminMasteryDistribution,
    AdminMasterySummary,
    AdminMetricsAggregate,
    AdminMetricsWindow,
    AdminOverview,
    AdminProfileDimension,
    AdminResourceGateReview,
    AdminResourceReviewItem,
    AdminResourceReviewPage,
    AdminResourceStats,
    AdminResourceTypeStat,
    AdminStudentPage,
    AdminStudentProfile,
    AdminStudentProgress,
    AdminStudentSummary,
    PageMetadata,
)
from app.models import (
    AgentRun,
    AgentToolCall,
    EvidenceEvent,
    LearningPath,
    LearningPathStatus,
    LearningPathStep,
    LearningResourceRecord,
    MasteryState,
    MasteryStatus,
    ProfileDimensionScore,
    ProfileVersion,
    ProviderCallRecord,
    ResourceJobRecord,
    ResourceReviewRecord,
    ReviewSchedule,
    ReviewStatus,
    Role,
    RoleName,
    TaskInstance,
    TaskInstanceStatus,
    User,
    UserRole,
    UserStatus,
)
from app.resources import ResourceArtifactStatus

_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|secret|password|authorization|cookie|token|credential)", re.IGNORECASE
)
_MAX_REDACTION_DEPTH = 8
_MAX_COLLECTION_ITEMS = 128
_MAX_TEXT_LENGTH = 4096


class AdminReadNotFound(LookupError):
    """An object is absent from the requesting administrator's tenant."""


def _page(number: int, size: int, total: int) -> PageMetadata:
    return PageMetadata(
        number=number,
        size=size,
        total_items=total,
        total_pages=math.ceil(total / size) if total else 0,
    )


def _scoped_student(db: Session, *, tenant_id: UUID, student_id: UUID) -> User:
    student = db.scalar(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            User.id == student_id,
            User.tenant_id == tenant_id,
            Role.name == RoleName.STUDENT.value,
        )
    )
    if student is None:
        raise AdminReadNotFound("student not found")
    return student


def list_students(
    db: Session,
    *,
    tenant_id: UUID,
    page: int,
    page_size: int,
    query: str | None = None,
    user_status: UserStatus | None = None,
) -> AdminStudentPage:
    predicates = [
        User.tenant_id == tenant_id,
        Role.name == RoleName.STUDENT.value,
    ]
    if query:
        pattern = f"%{query.strip()}%"
        predicates.append(
            or_(
                User.email.ilike(pattern),
                User.student_no.ilike(pattern),
                User.display_name.ilike(pattern),
            )
        )
    if user_status is not None:
        predicates.append(User.status == user_status)
    base = (
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(*predicates)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    users = list(
        db.scalars(
            base.order_by(User.created_at.desc(), User.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    items: list[AdminStudentSummary] = []
    for user in users:
        profile_version = (
            db.scalar(
                select(func.max(ProfileVersion.version)).where(
                    ProfileVersion.tenant_id == tenant_id,
                    ProfileVersion.student_id == user.id,
                )
            )
            or 0
        )
        completed_tasks = (
            db.scalar(
                select(func.count())
                .select_from(TaskInstance)
                .where(
                    TaskInstance.tenant_id == tenant_id,
                    TaskInstance.student_id == user.id,
                    TaskInstance.status == TaskInstanceStatus.COMPLETED,
                )
            )
            or 0
        )
        due_reviews = (
            db.scalar(
                select(func.count())
                .select_from(ReviewSchedule)
                .where(
                    ReviewSchedule.tenant_id == tenant_id,
                    ReviewSchedule.student_id == user.id,
                    ReviewSchedule.status == ReviewStatus.DUE,
                )
            )
            or 0
        )
        items.append(
            AdminStudentSummary(
                id=user.id,
                email=user.email,
                student_no=user.student_no,
                display_name=user.display_name,
                status=user.status.value,
                created_at=user.created_at,
                profile_version=profile_version,
                completed_tasks=completed_tasks,
                due_reviews=due_reviews,
            )
        )
    return AdminStudentPage(items=items, page=_page(page, page_size, total))


def get_student_profile(db: Session, *, tenant_id: UUID, student_id: UUID) -> AdminStudentProfile:
    _scoped_student(db, tenant_id=tenant_id, student_id=student_id)
    profile = db.scalar(
        select(ProfileVersion)
        .where(
            ProfileVersion.tenant_id == tenant_id,
            ProfileVersion.student_id == student_id,
        )
        .order_by(ProfileVersion.version.desc())
        .limit(1)
    )
    if profile is None:
        return AdminStudentProfile(student_id=student_id, version=0, dimensions=[], created_at=None)
    rows = list(
        db.scalars(
            select(ProfileDimensionScore)
            .where(
                ProfileDimensionScore.tenant_id == tenant_id,
                ProfileDimensionScore.profile_version_id == profile.id,
            )
            .order_by(ProfileDimensionScore.dimension, ProfileDimensionScore.scope_key)
        )
    )
    return AdminStudentProfile(
        student_id=student_id,
        version=profile.version,
        dimensions=[
            AdminProfileDimension(
                dimension=row.dimension.value,
                scope_key=row.scope_key,
                score=row.score,
                confidence=row.confidence,
                support_level=row.support_level,
            )
            for row in rows
        ],
        created_at=profile.created_at,
    )


def get_student_progress(db: Session, *, tenant_id: UUID, student_id: UUID) -> AdminStudentProgress:
    _scoped_student(db, tenant_id=tenant_id, student_id=student_id)
    path = db.scalar(
        select(LearningPath)
        .where(
            LearningPath.tenant_id == tenant_id,
            LearningPath.student_id == student_id,
            LearningPath.status == LearningPathStatus.CURRENT,
        )
        .order_by(LearningPath.updated_at.desc(), LearningPath.id.desc())
        .limit(1)
    )
    current_node_id: UUID | None = None
    if path is not None:
        current_node_id = db.scalar(
            select(LearningPathStep.node_id)
            .where(
                LearningPathStep.tenant_id == tenant_id,
                LearningPathStep.path_id == path.id,
            )
            .order_by(LearningPathStep.position.asc())
            .limit(1)
        )
    completed_tasks = (
        db.scalar(
            select(func.count())
            .select_from(TaskInstance)
            .where(
                TaskInstance.tenant_id == tenant_id,
                TaskInstance.student_id == student_id,
                TaskInstance.status == TaskInstanceStatus.COMPLETED,
            )
        )
        or 0
    )
    due_reviews = (
        db.scalar(
            select(func.count())
            .select_from(ReviewSchedule)
            .where(
                ReviewSchedule.tenant_id == tenant_id,
                ReviewSchedule.student_id == student_id,
                ReviewSchedule.status == ReviewStatus.DUE,
            )
        )
        or 0
    )
    mastery_rows = db.execute(
        select(MasteryState.status, func.count())
        .where(
            MasteryState.tenant_id == tenant_id,
            MasteryState.student_id == student_id,
        )
        .group_by(MasteryState.status)
    ).all()
    last_active = db.scalar(
        select(func.max(EvidenceEvent.created_at)).where(
            EvidenceEvent.tenant_id == tenant_id,
            EvidenceEvent.student_id == student_id,
        )
    )
    return AdminStudentProgress(
        student_id=student_id,
        current_path_id=None if path is None else path.id,
        current_node_id=current_node_id,
        completed_tasks=completed_tasks,
        due_reviews=due_reviews,
        mastery_counts={status.value: count for status, count in mastery_rows},
        last_active_at=last_active,
    )


def list_student_evidence(
    db: Session,
    *,
    tenant_id: UUID,
    student_id: UUID,
    page: int,
    page_size: int,
    event_type: str | None = None,
) -> AdminEvidencePage:
    _scoped_student(db, tenant_id=tenant_id, student_id=student_id)
    predicates = [
        EvidenceEvent.tenant_id == tenant_id,
        EvidenceEvent.student_id == student_id,
    ]
    if event_type:
        predicates.append(EvidenceEvent.event_type == event_type)
    total = db.scalar(select(func.count()).select_from(EvidenceEvent).where(*predicates)) or 0
    rows = list(
        db.scalars(
            select(EvidenceEvent)
            .where(*predicates)
            .order_by(EvidenceEvent.created_at.desc(), EvidenceEvent.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return AdminEvidencePage(
        items=[
            AdminEvidenceItem(
                id=row.id,
                event_id=row.event_id,
                event_type=row.event_type,
                course_id=row.course_id,
                node_id=row.node_id,
                task_id=row.task_id,
                trace_id=row.trace_id,
                evidence_confidence=row.evidence_confidence,
                created_at=row.created_at,
            )
            for row in rows
        ],
        page=_page(page, page_size, total),
    )


def get_mastery_summary(
    db: Session, *, tenant_id: UUID, course_id: UUID | None
) -> AdminMasterySummary:
    predicates = [MasteryState.tenant_id == tenant_id]
    review_predicates = [ReviewSchedule.tenant_id == tenant_id]
    if course_id is not None:
        predicates.append(MasteryState.course_id == course_id)
        review_predicates.append(ReviewSchedule.course_id == course_id)
    rows = db.execute(
        select(MasteryState.status, func.count()).where(*predicates).group_by(MasteryState.status)
    ).all()
    counts = {status.value: count for status, count in rows}
    total = sum(counts.values())
    due_reviews = (
        db.scalar(
            select(func.count())
            .select_from(ReviewSchedule)
            .where(*review_predicates, ReviewSchedule.status == ReviewStatus.DUE)
        )
        or 0
    )
    stable = counts.get("STABLE_MASTERY", 0)
    return AdminMasterySummary(
        course_id=course_id,
        total_states=total,
        counts=counts,
        due_reviews=due_reviews,
        stable_ratio=stable / total if total else 0.0,
    )


def list_resource_reviews(
    db: Session, *, tenant_id: UUID, page: int, page_size: int
) -> AdminResourceReviewPage:
    predicates = [
        LearningResourceRecord.tenant_id == tenant_id,
        LearningResourceRecord.status.in_(
            [ResourceArtifactStatus.STAGED, ResourceArtifactStatus.REVIEWING]
        ),
    ]
    total = (
        db.scalar(select(func.count()).select_from(LearningResourceRecord).where(*predicates)) or 0
    )
    rows = list(
        db.scalars(
            select(LearningResourceRecord)
            .where(*predicates)
            .order_by(LearningResourceRecord.created_at.asc(), LearningResourceRecord.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    items: list[AdminResourceReviewItem] = []
    for resource in rows:
        job = db.scalar(
            select(ResourceJobRecord).where(
                ResourceJobRecord.id == resource.job_id,
                ResourceJobRecord.tenant_id == tenant_id,
            )
        )
        if job is None:
            continue
        reviews = list(
            db.scalars(
                select(ResourceReviewRecord)
                .where(ResourceReviewRecord.resource_id == resource.id)
                .order_by(ResourceReviewRecord.gate, ResourceReviewRecord.version)
            )
        )
        items.append(
            AdminResourceReviewItem(
                resource_id=resource.id,
                job_id=resource.job_id,
                student_id=job.student_id,
                resource_type=resource.resource_type.value,
                version=resource.version,
                status=resource.status.value,
                content_digest=resource.content_digest,
                created_at=resource.created_at,
                gates=[
                    AdminResourceGateReview(
                        gate=review.gate.value,
                        version=review.version,
                        passed=review.passed,
                        findings=review.findings,
                        reviewer=review.reviewer,
                        created_at=review.created_at,
                    )
                    for review in reviews
                ],
            )
        )
    return AdminResourceReviewPage(items=items, page=_page(page, page_size, total))


def get_admin_overview(db: Session, *, tenant_id: UUID) -> AdminOverview:
    """Return live tenant-scoped aggregate counts for the admin overview.

    Replaces the V1.0 frontend hardcoded values (``活跃学生 248`` /
    ``资源审校 7``). Every count is filtered by ``tenant_id`` so cross-tenant
    data never leaks; predicates mirror the existing detail endpoints:
    active students follow ``_scoped_student`` (STUDENT role + ACTIVE
    status), pending registrations mirror ``/admin/registrations/pending``,
    resource reviews mirror ``list_resource_reviews`` (STAGED/REVIEWING),
    and due reviews mirror ``get_mastery_summary``.
    """
    active_students = (
        db.scalar(
            select(func.count())
            .select_from(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                User.tenant_id == tenant_id,
                User.status == UserStatus.ACTIVE,
                Role.name == RoleName.STUDENT.value,
            )
        )
        or 0
    )
    pending_registrations = (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.tenant_id == tenant_id, User.status == UserStatus.PENDING)
        )
        or 0
    )
    resource_reviews = (
        db.scalar(
            select(func.count())
            .select_from(LearningResourceRecord)
            .where(
                LearningResourceRecord.tenant_id == tenant_id,
                LearningResourceRecord.status.in_(
                    [ResourceArtifactStatus.STAGED, ResourceArtifactStatus.REVIEWING]
                ),
            )
        )
        or 0
    )
    due_reviews = (
        db.scalar(
            select(func.count())
            .select_from(ReviewSchedule)
            .where(
                ReviewSchedule.tenant_id == tenant_id,
                ReviewSchedule.status == ReviewStatus.DUE,
            )
        )
        or 0
    )
    return AdminOverview(
        active_students=active_students,
        pending_registrations=pending_registrations,
        resource_reviews=resource_reviews,
        due_reviews=due_reviews,
    )


# Hourly buckets stay readable for short windows; daily buckets keep long
# windows chartable without leaking thousands of empty slots to the FE.
_HOURLY_WINDOW_LIMIT = timedelta(hours=36)


def _resolve_metrics_window(
    since: datetime | None, until: datetime | None
) -> tuple[datetime, datetime, str, timedelta]:
    """Return ``(since, until, bucket_label, bucket_delta)`` for a metrics query.

    Defaults to the trailing seven days and picks ``hour`` granularity for any
    window no longer than 36 hours (so a one-day chart resolves per-hour
    spikes); otherwise it switches to ``day`` to keep the series compact.
    """
    end = until or datetime.now(UTC)
    start = since or end - timedelta(days=7)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("timezone-aware metrics window required")
    if start >= end:
        raise ValueError("metrics window must be positive")
    hourly = (end - start) <= _HOURLY_WINDOW_LIMIT
    bucket_delta = timedelta(hours=1) if hourly else timedelta(days=1)
    bucket_label = "hour" if hourly else "day"
    return start, end, bucket_label, bucket_delta


def _percentile(sorted_values: list[int], q: float) -> int | None:
    if not sorted_values:
        return None
    index = max(0, min(len(sorted_values) - 1, math.ceil(len(sorted_values) * q) - 1))
    return sorted_values[index]


def _bucket_starts(start: datetime, end: datetime, bucket_delta: timedelta) -> list[datetime]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("timezone-aware metrics window required")
    buckets: list[datetime] = []
    if bucket_delta == timedelta(days=1):
        cursor = start.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        if cursor > start:
            cursor -= bucket_delta
    else:
        cursor = start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    while cursor < end:
        if cursor >= start:
            buckets.append(cursor)
        cursor += bucket_delta
    if not buckets:
        buckets.append(start)
    return buckets


def _api_usage_series(
    db: Session,
    *,
    tenant_id: UUID,
    start: datetime,
    end: datetime,
    bucket_starts: list[datetime],
    bucket_delta: timedelta,
) -> AdminApiUsageSeries:
    rows = list(
        db.scalars(
            select(ProviderCallRecord).where(
                ProviderCallRecord.tenant_id == tenant_id,
                ProviderCallRecord.created_at >= start,
                ProviderCallRecord.created_at <= end,
            )
        )
    )
    grouped: dict[datetime, list[Any]] = {bucket: [] for bucket in bucket_starts}
    for row in rows:
        bucket = _bucket_for(row.created_at, bucket_starts, bucket_delta)
        grouped.setdefault(bucket, []).append(row)
    buckets: list[AdminApiUsageBucket] = []
    for bucket_start in bucket_starts:
        calls = grouped.get(bucket_start, [])
        if not calls:
            buckets.append(
                AdminApiUsageBucket(
                    bucket_start=bucket_start,
                    calls=0,
                    p50_latency_ms=None,
                    p95_latency_ms=None,
                    error_rate=0.0,
                    throttle_rate=0.0,
                )
            )
            continue
        latencies = sorted(call.latency_ms for call in calls)
        errors = sum(call.outcome != "SUCCEEDED" for call in calls)
        throttled = sum(call.rate_limited for call in calls)
        buckets.append(
            AdminApiUsageBucket(
                bucket_start=bucket_start,
                calls=len(calls),
                p50_latency_ms=_percentile(latencies, 0.5),
                p95_latency_ms=_percentile(latencies, 0.95),
                error_rate=errors / len(calls),
                throttle_rate=throttled / len(calls),
            )
        )
    return AdminApiUsageSeries(buckets=buckets)


def _bucket_for(
    timestamp: datetime,
    bucket_starts: list[datetime],
    bucket_delta: timedelta,
) -> datetime:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    if bucket_delta == timedelta(days=1):
        aligned = timestamp.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        aligned = timestamp.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    # walk back to the most recent bucket_start <= aligned
    candidate = aligned
    while candidate not in bucket_starts and candidate >= bucket_starts[0]:
        candidate -= bucket_delta
    if candidate in bucket_starts:
        return candidate
    # timestamp predates the first bucket; clamp to the first bucket
    return bucket_starts[0]


def _mastery_distribution(
    db: Session,
    *,
    tenant_id: UUID,
    course_id: UUID | None,
    node_id: UUID | None,
) -> AdminMasteryDistribution:
    predicates: list[Any] = [MasteryState.tenant_id == tenant_id]
    if course_id is not None:
        predicates.append(MasteryState.course_id == course_id)
    if node_id is not None:
        predicates.append(MasteryState.node_id == node_id)
    rows = db.execute(
        select(MasteryState.status, func.count()).where(*predicates).group_by(MasteryState.status)
    ).all()
    counts = {status.value: 0 for status in MasteryStatus}
    for status, count in rows:
        counts[status.value] = count
    return AdminMasteryDistribution(
        course_id=course_id,
        node_id=node_id,
        total_states=sum(counts.values()),
        counts=counts,
    )


def _agent_timeline(
    db: Session,
    *,
    tenant_id: UUID,
    start: datetime,
    end: datetime,
    bucket_starts: list[datetime],
    bucket_delta: timedelta,
) -> AdminAgentTimeline:
    rows = list(
        db.scalars(
            select(AgentRun).where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.created_at >= start,
                AgentRun.created_at <= end,
            )
        )
    )
    grouped: dict[datetime, list[Any]] = {bucket: [] for bucket in bucket_starts}
    for row in rows:
        bucket = _bucket_for(row.created_at, bucket_starts, bucket_delta)
        grouped.setdefault(bucket, []).append(row)
    buckets: list[AdminAgentTimelinePoint] = []
    for bucket_start in bucket_starts:
        runs = grouped.get(bucket_start, [])
        succeeded = sum(1 for run in runs if run.status == "SUCCEEDED")
        failed = sum(1 for run in runs if run.status not in ("SUCCEEDED", "QUEUED", "RUNNING"))
        fallback = sum(1 for run in runs if run.fallback_used)
        buckets.append(
            AdminAgentTimelinePoint(
                bucket_start=bucket_start,
                total=len(runs),
                succeeded=succeeded,
                failed=failed,
                fallback_used=fallback,
            )
        )
    return AdminAgentTimeline(buckets=buckets)


def _resource_stats(
    db: Session,
    *,
    tenant_id: UUID,
    start: datetime,
    end: datetime,
    course_id: UUID | None,
) -> AdminResourceStats:
    # LearningResourceRecord has no course_id; ResourceJobRecord does, so join
    # when the optional course filter is set.
    predicates: list[Any] = [LearningResourceRecord.tenant_id == tenant_id]
    stmt = select(LearningResourceRecord)
    if course_id is not None:
        stmt = stmt.join(ResourceJobRecord, ResourceJobRecord.id == LearningResourceRecord.job_id)
        predicates.append(ResourceJobRecord.course_id == course_id)
    rows = list(db.scalars(stmt.where(*predicates)))
    groups: dict[str, list[Any]] = {}
    for row in rows:
        groups.setdefault(row.resource_type.value, []).append(row)
    items: list[AdminResourceTypeStat] = []
    for resource_type, artifacts in sorted(groups.items()):
        total = len(artifacts)
        staged = sum(1 for a in artifacts if a.status == ResourceArtifactStatus.STAGED)
        reviewing = sum(1 for a in artifacts if a.status == ResourceArtifactStatus.REVIEWING)
        published = sum(1 for a in artifacts if a.status == ResourceArtifactStatus.PUBLISHED)
        rejected = sum(1 for a in artifacts if a.status == ResourceArtifactStatus.REJECTED)
        durations: list[float] = []
        for artifact in artifacts:
            created = artifact.created_at
            updated = artifact.updated_at
            if created is not None and updated is not None and updated >= created:
                durations.append(max(0.0, (updated - created).total_seconds() * 1000.0))
        items.append(
            AdminResourceTypeStat(
                resource_type=resource_type,
                total=total,
                staged=staged,
                reviewing=reviewing,
                published=published,
                rejected=rejected,
                success_rate=published / total if total else 0.0,
                avg_generation_ms=sum(durations) / len(durations) if durations else None,
            )
        )
    return AdminResourceStats(items=items)


def get_admin_metrics(
    db: Session,
    *,
    tenant_id: UUID,
    since: datetime | None,
    until: datetime | None,
    node_id: UUID | None = None,
    course_id: UUID | None = None,
) -> AdminMetricsAggregate:
    """Return the BE-028 advanced metrics aggregate for FE-025/FE-026.

    Every series is scoped to ``tenant_id``. ``api_usage`` and ``agent_timeline``
    aggregate Provider call / AgentRun records across the resolved window using
    hourly buckets for windows up to 36h and daily buckets beyond that.
    ``mastery_distribution`` honours optional ``course_id``/``node_id`` filters,
    and ``resource_stats`` reports per-type publication outcomes (and the
    optional ``course_id`` filter via the parent resource job).
    """
    start, end, bucket_label, bucket_delta = _resolve_metrics_window(since, until)
    bucket_starts = _bucket_starts(start, end, bucket_delta)
    return AdminMetricsAggregate(
        window=AdminMetricsWindow(
            since=start,
            until=end,
            bucket=bucket_label,
            bucket_count=len(bucket_starts),
        ),
        api_usage=_api_usage_series(
            db,
            tenant_id=tenant_id,
            start=start,
            end=end,
            bucket_starts=bucket_starts,
            bucket_delta=bucket_delta,
        ),
        mastery_distribution=_mastery_distribution(
            db, tenant_id=tenant_id, course_id=course_id, node_id=node_id
        ),
        agent_timeline=_agent_timeline(
            db,
            tenant_id=tenant_id,
            start=start,
            end=end,
            bucket_starts=bucket_starts,
            bucket_delta=bucket_delta,
        ),
        resource_stats=_resource_stats(
            db, tenant_id=tenant_id, start=start, end=end, course_id=course_id
        ),
    )


def redact_admin_snapshot(value: Any, *, depth: int = 0) -> Any:
    if depth >= _MAX_REDACTION_DEPTH:
        return "[truncated]"
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_COLLECTION_ITEMS:
                redacted["_truncated"] = True
                break
            safe_key = str(key)[:128]
            redacted[safe_key] = (
                "***"
                if _SENSITIVE_KEY.search(safe_key)
                else redact_admin_snapshot(item, depth=depth + 1)
            )
        return redacted
    if isinstance(value, list):
        return [
            redact_admin_snapshot(item, depth=depth + 1) for item in value[:_MAX_COLLECTION_ITEMS]
        ]
    if isinstance(value, str):
        return value[:_MAX_TEXT_LENGTH]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[unsupported]"


def get_agent_run(db: Session, *, tenant_id: UUID, external_run_id: str) -> AdminAgentRunView:
    run = db.scalar(
        select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.external_run_id == external_run_id,
        )
    )
    if run is None:
        raise AdminReadNotFound("agent run not found")
    tools = list(
        db.scalars(
            select(AgentToolCall)
            .where(
                AgentToolCall.tenant_id == tenant_id,
                AgentToolCall.agent_run_id == run.id,
            )
            .order_by(AgentToolCall.sequence.asc())
        )
    )
    return AdminAgentRunView(
        external_run_id=run.external_run_id,
        event_id=run.event_id,
        trace_id=run.trace_id,
        student_id=run.student_id,
        status=run.status,
        route=run.route,
        latest_sequence=run.latest_sequence,
        checkpoint_thread_id=run.checkpoint_thread_id,
        latest_checkpoint_id=run.latest_checkpoint_id,
        fallback_used=run.fallback_used,
        error_code=run.error_code,
        input_snapshot=redact_admin_snapshot(run.safe_input_snapshot),
        output_snapshot=redact_admin_snapshot(run.safe_output_snapshot),
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        tool_calls=[
            AdminAgentToolCall(
                sequence=tool.sequence,
                node=tool.node,
                tool_name=tool.tool_name,
                event_type=tool.event_type,
                status=tool.status,
                argument_digest=tool.argument_digest,
                result_digest=tool.result_digest,
                latency_ms=tool.latency_ms,
                retry_count=tool.retry_count,
                error_code=tool.error_code,
                occurred_at=tool.occurred_at,
            )
            for tool in tools
        ],
    )
