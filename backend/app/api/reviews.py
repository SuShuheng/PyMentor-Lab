"""Student due-review query and reschedule command (BE-004)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.command_idempotency import begin_command, scope_for_request
from app.contracts.learning import ReviewRescheduleRequest, ReviewView
from app.db import get_db
from app.evidence import record_audit
from app.idempotency import save_response
from app.models import ReviewSchedule, ReviewStatus, User
from app.rbac import get_current_user
from app.reviews import reschedule_review
from app.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/reviews", tags=["learning-reviews"])


def _review_view(review: ReviewSchedule) -> ReviewView:
    return ReviewView(
        id=str(review.id),
        course_id=str(review.course_id),
        node_id=str(review.node_id),
        scenario_key=review.scenario_key,
        due_at=review.due_at.isoformat(),
        status=review.status.value,
        reschedule_count=review.reschedule_count,
        version=review.version,
    )


@router.get("/due", response_model=list[ReviewView])
async def get_due_reviews(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[ReviewView]:
    reviews = list(
        db.scalars(
            select(ReviewSchedule)
            .where(
                ReviewSchedule.tenant_id == user.tenant_id,
                ReviewSchedule.student_id == user.id,
                ReviewSchedule.status == ReviewStatus.DUE,
            )
            .order_by(ReviewSchedule.due_at, ReviewSchedule.id)
        )
    )
    return [_review_view(review) for review in reviews]


@router.post("/{review_id}/reschedule", response_model=ReviewView)
async def postpone_review(
    review_id: UUID,
    body: ReviewRescheduleRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReviewView | JSONResponse:
    review = db.scalar(
        select(ReviewSchedule).where(
            ReviewSchedule.id == review_id,
            ReviewSchedule.tenant_id == user.tenant_id,
            ReviewSchedule.student_id == user.id,
        )
    )
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review not found")
    try:
        requested_due_at = datetime.fromisoformat(body.due_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="due_at must be an ISO-8601 timestamp",
        ) from exc

    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    cached = begin_command(db, scope)
    if cached is not None:
        return JSONResponse(
            content=cached.response_body or {},
            status_code=cached.response_status or status.HTTP_200_OK,
        )

    trace_id = str(request.state.trace_id)
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        updated = reschedule_review(
            db,
            review_id=review.id,
            requested_due_at=requested_due_at,
            now=datetime.now(UTC),
            expected_version=body.expected_version,
        )
        view = _review_view(updated)
        response_body = view.model_dump(mode="json")
        record_audit(
            db,
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            action="REVIEW_RESCHEDULED",
            resource_type="review_schedule",
            resource_id=str(updated.id),
            trace_id=trace_id,
            detail={"due_at": updated.due_at.isoformat()},
        )
        uow.publish(
            event_type="REVIEW_RESCHEDULED",
            aggregate_type="review_schedule",
            aggregate_id=str(updated.id),
            tenant_id=user.tenant_id,
            trace_id=trace_id,
            payload={"due_at": updated.due_at.isoformat()},
        )
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_200_OK,
            response_body=response_body,
        )
        uow.commit()
    return view
