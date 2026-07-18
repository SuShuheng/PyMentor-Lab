"""Student-scoped current mastery query (BE-004)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.learning import MasteryView
from app.db import get_db
from app.models import MasteryState, ReviewSchedule, ReviewStatus, User
from app.rbac import get_current_user

router = APIRouter(prefix="/api/v1/mastery", tags=["learning-mastery"])


@router.get("", response_model=list[MasteryView])
async def get_mastery(
    course_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MasteryView]:
    statement = select(MasteryState).where(
        MasteryState.tenant_id == user.tenant_id,
        MasteryState.student_id == user.id,
    )
    if course_id is not None:
        statement = statement.where(MasteryState.course_id == course_id)
    states = list(db.scalars(statement.order_by(MasteryState.course_id, MasteryState.node_id)))
    result: list[MasteryView] = []
    for state in states:
        review_due_at = db.scalar(
            select(ReviewSchedule.due_at)
            .where(
                ReviewSchedule.mastery_state_id == state.id,
                ReviewSchedule.status.in_([ReviewStatus.SCHEDULED, ReviewStatus.DUE]),
            )
            .order_by(ReviewSchedule.due_at)
            .limit(1)
        )
        result.append(
            MasteryView(
                id=str(state.id),
                course_id=str(state.course_id),
                node_id=str(state.node_id),
                status=state.status.value,
                version=state.version,
                review_due_at=(review_due_at.isoformat() if review_due_at else None),
            )
        )
    return result
