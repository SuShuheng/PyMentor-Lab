"""Least-privilege BE-010 administrative query routes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.admin_queries import (
    AdminReadNotFound,
    get_admin_metrics,
    get_admin_overview,
    get_agent_run,
    get_mastery_summary,
    get_student_profile,
    get_student_progress,
    list_resource_reviews,
    list_student_evidence,
    list_students,
)
from app.contracts.admin import (
    AdminAgentRunView,
    AdminEvidencePage,
    AdminMasterySummary,
    AdminMetricsAggregate,
    AdminOverview,
    AdminResourceReviewPage,
    AdminStudentPage,
    AdminStudentProfile,
    AdminStudentProgress,
)
from app.db import get_db
from app.models import User, UserStatus
from app.rbac import require_admin, require_course_admin

router = APIRouter(prefix="/api/v1/admin", tags=["admin-operations"])


def _not_found(error: AdminReadNotFound) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


@router.get("/students", response_model=AdminStudentPage)
async def admin_students(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    user_status: UserStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> AdminStudentPage:
    return list_students(
        db,
        tenant_id=admin.tenant_id,
        page=page,
        page_size=page_size,
        query=q,
        user_status=user_status,
    )


@router.get("/students/{student_id}/profile", response_model=AdminStudentProfile)
async def admin_student_profile(
    student_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> AdminStudentProfile:
    try:
        return get_student_profile(db, tenant_id=admin.tenant_id, student_id=student_id)
    except AdminReadNotFound as error:
        raise _not_found(error) from error


@router.get("/students/{student_id}/progress", response_model=AdminStudentProgress)
async def admin_student_progress(
    student_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> AdminStudentProgress:
    try:
        return get_student_progress(db, tenant_id=admin.tenant_id, student_id=student_id)
    except AdminReadNotFound as error:
        raise _not_found(error) from error


@router.get("/students/{student_id}/evidence", response_model=AdminEvidencePage)
async def admin_student_evidence(
    student_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    event_type: str | None = Query(default=None, min_length=1, max_length=64),
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> AdminEvidencePage:
    try:
        return list_student_evidence(
            db,
            tenant_id=admin.tenant_id,
            student_id=student_id,
            page=page,
            page_size=page_size,
            event_type=event_type,
        )
    except AdminReadNotFound as error:
        raise _not_found(error) from error


@router.get("/mastery/summary", response_model=AdminMasterySummary)
async def admin_mastery_summary(
    course_id: UUID | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> AdminMasterySummary:
    return get_mastery_summary(db, tenant_id=admin.tenant_id, course_id=course_id)


@router.get("/overview", response_model=AdminOverview)
async def admin_overview(
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> AdminOverview:
    return get_admin_overview(db, tenant_id=admin.tenant_id)


@router.get("/metrics", response_model=AdminMetricsAggregate)
async def admin_metrics(
    since: datetime | None = None,
    until: datetime | None = None,
    node_id: UUID | None = None,
    course_id: UUID | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> AdminMetricsAggregate:
    if since is not None and until is not None and since >= until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="metrics window must be positive",
        )
    return get_admin_metrics(
        db,
        tenant_id=admin.tenant_id,
        since=since,
        until=until,
        node_id=node_id,
        course_id=course_id,
    )


@router.get("/resources/reviews", response_model=AdminResourceReviewPage)
async def admin_resource_reviews(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminResourceReviewPage:
    return list_resource_reviews(db, tenant_id=admin.tenant_id, page=page, page_size=page_size)


@router.get("/agent-runs/{external_run_id}", response_model=AdminAgentRunView)
async def admin_agent_run(
    external_run_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> AdminAgentRunView:
    if not external_run_id or len(external_run_id) > 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid agent run identity",
        )
    try:
        return get_agent_run(db, tenant_id=admin.tenant_id, external_run_id=external_run_id)
    except AdminReadNotFound as error:
        raise _not_found(error) from error
