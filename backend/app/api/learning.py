"""Student today's-work projection with due-review priority (BE-004)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.learning import TodayItem
from app.db import get_db
from app.models import (
    LearningPath,
    LearningPathStatus,
    LearningPathStep,
    ReviewSchedule,
    ReviewStatus,
    TaskDefinition,
    TaskVersion,
    User,
)
from app.rbac import get_current_user

router = APIRouter(prefix="/api/v1/learning", tags=["learning"])


@router.get("/today", response_model=list[TodayItem])
async def get_today(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[TodayItem]:
    due_reviews = list(
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
    result = [
        TodayItem(
            id=str(review.id),
            course_id=str(review.course_id),
            node_id=str(review.node_id),
            kind="REVIEW",
            estimated_minutes=15,
            due_at=review.due_at.isoformat(),
            task_version_id=None,
        )
        for review in due_reviews
    ]

    path = db.scalar(
        select(LearningPath)
        .where(
            LearningPath.tenant_id == user.tenant_id,
            LearningPath.student_id == user.id,
            LearningPath.status == LearningPathStatus.CURRENT,
        )
        .order_by(LearningPath.updated_at.desc(), LearningPath.id)
        .limit(1)
    )
    if path is None:
        return result
    steps = list(
        db.scalars(
            select(LearningPathStep)
            .where(LearningPathStep.path_id == path.id)
            .order_by(LearningPathStep.position)
        )
    )
    for step in steps:
        task_version_id = db.scalar(
            select(TaskVersion.id)
            .join(TaskDefinition, TaskDefinition.id == TaskVersion.definition_id)
            .where(
                TaskVersion.tenant_id == user.tenant_id,
                TaskVersion.published.is_(True),
                TaskDefinition.node_id == step.node_id,
            )
            .order_by(TaskVersion.version.desc())
            .limit(1)
        )
        result.append(
            TodayItem(
                id=str(step.id),
                course_id=str(path.course_id),
                node_id=str(step.node_id),
                kind=step.kind.value,
                estimated_minutes=step.estimated_minutes,
                due_at=None,
                task_version_id=(str(task_version_id) if task_version_id else None),
            )
        )
    return result
