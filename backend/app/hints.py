"""Ordered, versioned static hint usage policy for code tasks."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CodeRevision, HintSource, HintUsage, TaskInstance
from app.task_policy import parse_task_policy


class InvalidHintRequest(ValueError):
    pass


def record_hint_usage(
    db: Session,
    *,
    task: TaskInstance,
    level: int,
    revision_id: UUID | None,
    now: datetime,
) -> HintUsage:
    locked_task = db.scalar(
        select(TaskInstance).where(TaskInstance.id == task.id).with_for_update()
    )
    if locked_task is None:
        raise InvalidHintRequest("task not found")
    policy = parse_task_policy(locked_task.snapshot).hints
    if level > policy.max_level:
        raise InvalidHintRequest(f"maximum hint level is {policy.max_level}")

    history = list(
        db.scalars(
            select(HintUsage)
            .where(HintUsage.task_instance_id == locked_task.id)
            .order_by(HintUsage.sequence)
            .with_for_update()
        )
    )
    expected_level = (history[-1].level if history else 0) + 1
    if level != expected_level:
        raise InvalidHintRequest(f"next hint level is {expected_level}")

    if revision_id is not None:
        revision = db.scalar(
            select(CodeRevision).where(
                CodeRevision.id == revision_id,
                CodeRevision.task_instance_id == locked_task.id,
                CodeRevision.student_id == locked_task.student_id,
            )
        )
        if revision is None:
            raise InvalidHintRequest("revision does not belong to task")

    hint = policy.hints[level - 1]
    usage = HintUsage(
        tenant_id=locked_task.tenant_id,
        student_id=locked_task.student_id,
        task_instance_id=locked_task.id,
        revision_id=revision_id,
        sequence=(history[-1].sequence if history else 0) + 1,
        hint_key=hint.key,
        level=hint.level,
        cost=hint.independence_cost,
        content=hint.content,
        source=HintSource.STATIC,
        created_at=now,
    )
    locked_task.version += 1
    db.add(usage)
    db.flush()
    return usage
