"""Tenant-scoped read models for BE-010 administrative visibility."""

from __future__ import annotations

import math
import re
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.contracts.admin import (
    AdminAgentRunView,
    AdminAgentToolCall,
    AdminEvidenceItem,
    AdminEvidencePage,
    AdminMasterySummary,
    AdminProfileDimension,
    AdminResourceGateReview,
    AdminResourceReviewItem,
    AdminResourceReviewPage,
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
    ProfileDimensionScore,
    ProfileVersion,
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
