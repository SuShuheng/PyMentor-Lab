"""Current validated learning-path query (BE-004)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.learning import PathSnapshot, PathStepView
from app.db import get_db
from app.models import LearningPath, LearningPathStatus, LearningPathStep, User
from app.rbac import get_current_user

router = APIRouter(prefix="/api/v1/paths", tags=["learning-paths"])


@router.get("/current", response_model=PathSnapshot)
async def get_current_path(
    course_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PathSnapshot:
    statement = (
        select(LearningPath)
        .where(
            LearningPath.tenant_id == user.tenant_id,
            LearningPath.student_id == user.id,
            LearningPath.status == LearningPathStatus.CURRENT,
        )
        .order_by(LearningPath.updated_at.desc(), LearningPath.id)
        .limit(1)
    )
    if course_id is not None:
        statement = statement.where(LearningPath.course_id == course_id)
    path = db.scalar(statement)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="current path not found")
    steps = list(
        db.scalars(
            select(LearningPathStep)
            .where(LearningPathStep.path_id == path.id)
            .order_by(LearningPathStep.position)
        )
    )
    return PathSnapshot(
        id=str(path.id),
        course_id=str(path.course_id),
        version=path.version,
        status=path.status.value,
        steps=[
            PathStepView(
                id=str(step.id),
                position=step.position,
                node_id=str(step.node_id),
                kind=step.kind.value,
                estimated_minutes=step.estimated_minutes,
                scenario_key=step.scenario_key,
                validation_status=step.validation_status.value,
            )
            for step in steps
        ],
    )
