"""Task start and evidence-backed submission commands (BE-004)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.command_idempotency import begin_command, scope_for_request
from app.contracts.learning import (
    AssessmentSubmission,
    TaskStartResponse,
    TaskSubmissionResponse,
)
from app.db import get_db
from app.evidence import record_audit
from app.idempotency import save_response
from app.mastery import AssessmentFacts, MasteryPolicy, record_assessment_and_decide
from app.models import (
    EvidenceEvent,
    ReviewSchedule,
    ReviewStatus,
    TaskDefinition,
    TaskInstance,
    TaskInstanceStatus,
    TaskStatusHistory,
    TaskVersion,
    User,
)
from app.rbac import get_current_user
from app.task_compiler import start_task_instance
from app.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/tasks", tags=["learning-tasks"])


def _start_response(instance: TaskInstance) -> TaskStartResponse:
    return TaskStartResponse(
        id=str(instance.id),
        task_version_id=str(instance.task_version_id),
        status=instance.status.value,
        snapshot=instance.snapshot,
        started_at=instance.started_at.isoformat(),
        version=instance.version,
    )


def _assessment_facts(payload: dict[str, Any]) -> AssessmentFacts:
    required = {
        "correct",
        "hidden_tests_passed",
        "hints_used",
        "support_level",
        "independence_score",
        "transfer_score",
        "platform_error",
    }
    if not required <= payload.keys():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="assessment evidence payload is incomplete",
        )
    try:
        if not isinstance(payload["correct"], bool) or not isinstance(
            payload["hidden_tests_passed"], bool
        ):
            raise TypeError
        if not isinstance(payload["platform_error"], bool):
            raise TypeError
        return AssessmentFacts(
            correct=payload["correct"],
            hidden_tests_passed=payload["hidden_tests_passed"],
            hints_used=int(payload["hints_used"]),
            support_level=int(payload["support_level"]),
            independence_score=float(payload["independence_score"]),
            transfer_score=float(payload["transfer_score"]),
            platform_error=payload["platform_error"],
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="assessment evidence payload has invalid fact types",
        ) from exc


def _mastery_policy(version: TaskVersion) -> MasteryPolicy:
    raw = version.snapshot.get("mastery_policy")
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="task version has no mastery policy",
        )
    try:
        return MasteryPolicy(
            independence_min=float(raw["independence_min"]),
            transfer_min=float(raw["transfer_min"]),
            max_hints_for_mastery=int(raw["max_hints_for_mastery"]),
            review_delay_days=int(raw["review_delay_days"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="task mastery policy is incomplete",
        ) from exc


@router.post("/{task_version_id}/start", response_model=TaskStartResponse)
async def start_task(
    task_version_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskStartResponse | JSONResponse:
    version = db.scalar(
        select(TaskVersion).where(
            TaskVersion.id == task_version_id,
            TaskVersion.tenant_id == user.tenant_id,
            TaskVersion.published.is_(True),
        )
    )
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="published task version not found",
        )
    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    cached = begin_command(db, scope)
    if cached is not None:
        return JSONResponse(
            content=cached.response_body or {},
            status_code=cached.response_status or status.HTTP_200_OK,
        )

    trace_id = str(request.state.trace_id)
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        instance = start_task_instance(
            db,
            student_id=user.id,
            task_version_id=version.id,
            active_key="today",
        )
        view = _start_response(instance)
        response_body = view.model_dump(mode="json")
        record_audit(
            db,
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            action="TASK_STARTED",
            resource_type="task_instance",
            resource_id=str(instance.id),
            trace_id=trace_id,
        )
        uow.publish(
            event_type="TASK_STARTED",
            aggregate_type="task_instance",
            aggregate_id=str(instance.id),
            tenant_id=user.tenant_id,
            trace_id=trace_id,
            payload={"task_version_id": str(version.id)},
        )
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_200_OK,
            response_body=response_body,
        )
        uow.commit()
    return view


@router.post("/{task_instance_id}/submit", response_model=TaskSubmissionResponse)
async def submit_task(
    task_instance_id: UUID,
    body: AssessmentSubmission,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskSubmissionResponse | JSONResponse:
    instance = db.scalar(
        select(TaskInstance).where(
            TaskInstance.id == task_instance_id,
            TaskInstance.tenant_id == user.tenant_id,
            TaskInstance.student_id == user.id,
        )
    )
    if instance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    version = db.get(TaskVersion, instance.task_version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task version not found")
    definition = db.get(TaskDefinition, version.definition_id)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="task definition not found"
        )
    evidence = db.scalar(
        select(EvidenceEvent).where(
            EvidenceEvent.event_id == body.evidence_event_id,
            EvidenceEvent.tenant_id == user.tenant_id,
            EvidenceEvent.student_id == user.id,
            EvidenceEvent.course_id == definition.course_id,
            EvidenceEvent.node_id == definition.node_id,
            EvidenceEvent.task_id == instance.id,
            EvidenceEvent.event_type == "ASSESSMENT_RECORDED",
        )
    )
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="accepted assessment evidence not found in task scope",
        )
    facts = _assessment_facts(evidence.payload)
    policy = _mastery_policy(version)

    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    cached = begin_command(db, scope)
    if cached is not None:
        return JSONResponse(
            content=cached.response_body or {},
            status_code=cached.response_status or status.HTTP_200_OK,
        )
    if instance.version != body.expected_task_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"expected task version {body.expected_task_version}, actual {instance.version}",
        )
    if instance.status != TaskInstanceStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"task is {instance.status.value.lower()}",
        )

    now = datetime.now(UTC)
    trace_id = str(request.state.trace_id)
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        decision = record_assessment_and_decide(
            db,
            facts,
            policy=policy,
            tenant_id=user.tenant_id,
            student_id=user.id,
            course_id=definition.course_id,
            node_id=definition.node_id,
            evidence_event_id=evidence.event_id,
            now=now,
        )
        decision.assessment.task_instance_id = instance.id
        previous_status = instance.status
        instance.status = TaskInstanceStatus.COMPLETED
        instance.submitted_at = now
        instance.completed_at = now
        instance.version += 1
        db.add(
            TaskStatusHistory(
                tenant_id=user.tenant_id,
                task_instance_id=instance.id,
                from_status=previous_status,
                to_status=TaskInstanceStatus.COMPLETED,
                reason="ASSESSMENT_ACCEPTED",
                evidence_event_id=evidence.event_id,
                created_at=now,
            )
        )
        db.flush()

        if decision.state is None:
            submission_view = TaskSubmissionResponse(
                assessment_id=str(decision.assessment.id),
                task_instance_id=str(instance.id),
                course_id=str(definition.course_id),
                node_id=str(definition.node_id),
                status="PLATFORM_ERROR",
                version=0,
                review_due_at=None,
            )
        else:
            review = decision.review or db.scalar(
                select(ReviewSchedule)
                .where(
                    ReviewSchedule.mastery_state_id == decision.state.id,
                    ReviewSchedule.status.in_([ReviewStatus.SCHEDULED, ReviewStatus.DUE]),
                )
                .order_by(ReviewSchedule.due_at)
                .limit(1)
            )
            submission_view = TaskSubmissionResponse(
                assessment_id=str(decision.assessment.id),
                task_instance_id=str(instance.id),
                course_id=str(decision.state.course_id),
                node_id=str(decision.state.node_id),
                status=decision.state.status.value,
                version=decision.state.version,
                review_due_at=review.due_at.isoformat() if review else None,
            )
        response_body = submission_view.model_dump(mode="json")
        record_audit(
            db,
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            action="TASK_SUBMITTED",
            resource_type="task_instance",
            resource_id=str(instance.id),
            trace_id=trace_id,
            detail={"assessment_id": str(decision.assessment.id)},
        )
        uow.publish(
            event_type="TASK_SUBMITTED",
            aggregate_type="task_instance",
            aggregate_id=str(instance.id),
            tenant_id=user.tenant_id,
            trace_id=trace_id,
            payload={
                "assessment_id": str(decision.assessment.id),
                "mastery_status": response_body["status"],
            },
        )
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_200_OK,
            response_body=response_body,
        )
        uow.commit()
    return submission_view
