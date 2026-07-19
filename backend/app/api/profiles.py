"""Student profile query and dispute commands (BE-004)."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.command_idempotency import begin_command, scope_for_request
from app.contracts.learning import (
    OnboardingSubmissionRequest,
    OnboardingSubmissionView,
    ProfileDimensionView,
    ProfileDisputeRequest,
    ProfileDisputeView,
    ProfileSnapshot,
)
from app.db import get_db
from app.evidence import record_audit, record_evidence
from app.idempotency import save_response
from app.models import ProfileDimensionScore, ProfileVersion, User
from app.models.base import RoleName
from app.profile_projection import create_profile_dispute, project_onboarding
from app.rbac import get_current_user
from app.services import get_user_roles
from app.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/profiles", tags=["learning-profiles"])


@router.get("/current", response_model=ProfileSnapshot)
async def get_current_profile(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ProfileSnapshot:
    profile = db.scalar(
        select(ProfileVersion)
        .where(
            ProfileVersion.tenant_id == user.tenant_id,
            ProfileVersion.student_id == user.id,
        )
        .order_by(ProfileVersion.version.desc())
        .limit(1)
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="profile not found")
    scores = list(
        db.scalars(
            select(ProfileDimensionScore)
            .where(ProfileDimensionScore.profile_version_id == profile.id)
            .order_by(ProfileDimensionScore.dimension, ProfileDimensionScore.scope_key)
        )
    )
    return ProfileSnapshot(
        id=str(profile.id),
        student_id=str(profile.student_id),
        version=profile.version,
        source_event_id=profile.source_event_id,
        dimensions=[
            ProfileDimensionView(
                dimension=item.dimension.value,
                scope_key=item.scope_key,
                score=item.score,
                confidence=item.confidence,
                support_level=item.support_level,
            )
            for item in scores
        ],
    )


@router.post(
    "/disputes",
    status_code=status.HTTP_201_CREATED,
    response_model=ProfileDisputeView,
)
async def dispute_profile(
    body: ProfileDisputeRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProfileDisputeView | JSONResponse:
    try:
        profile_version_id = UUID(body.profile_version_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="profile_version_id must be a UUID",
        ) from exc
    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    cached = begin_command(db, scope)
    if cached is not None:
        return JSONResponse(
            content=cached.response_body or {},
            status_code=cached.response_status or status.HTTP_201_CREATED,
        )

    trace_id = str(request.state.trace_id)
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        dispute = create_profile_dispute(
            db,
            tenant_id=user.tenant_id,
            student_id=user.id,
            profile_version_id=profile_version_id,
            reason=body.reason,
        )
        view = ProfileDisputeView(
            id=str(dispute.id),
            profile_version_id=str(dispute.profile_version_id),
            reason=dispute.reason,
        )
        response_body = view.model_dump(mode="json")
        record_audit(
            db,
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            action="PROFILE_DISPUTED",
            resource_type="profile_dispute",
            resource_id=str(dispute.id),
            trace_id=trace_id,
        )
        uow.publish(
            event_type="PROFILE_DISPUTED",
            aggregate_type="profile_dispute",
            aggregate_id=str(dispute.id),
            tenant_id=user.tenant_id,
            trace_id=trace_id,
            payload={"profile_version_id": str(dispute.profile_version_id)},
        )
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_201_CREATED,
            response_body=response_body,
        )
        uow.commit()
    return view


def _require_student_role(db: Session, user: User) -> None:
    """Onboarding is a student-only command; non-students get 403."""

    if RoleName.STUDENT.value not in set(get_user_roles(db, user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="student role required",
        )


@router.post(
    "/onboarding",
    status_code=status.HTTP_201_CREATED,
    response_model=OnboardingSubmissionView,
)
async def submit_onboarding(
    body: OnboardingSubmissionRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OnboardingSubmissionView | JSONResponse:
    """Record onboarding answers as evidence and project them (BE-018).

    The answers flow through the deterministic profile projection as a
    low-confidence INDEPENDENCE_SUPPORT baseline (never auto-advancing
    mastery). A path-replan request is emitted via the Outbox so the existing
    compilation pipeline can re-evaluate eligibility without this endpoint
    touching ``persist_validated_path`` directly.
    """

    _require_student_role(db, user)
    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    cached = begin_command(db, scope)
    if cached is not None:
        return JSONResponse(
            content=cached.response_body or {},
            status_code=cached.response_status or status.HTTP_201_CREATED,
        )

    trace_id = str(request.state.trace_id)
    answers_payload = body.answers.model_dump(mode="json")
    evidence_event_id = f"evt_onboarding_{uuid4().hex}"
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        evidence = record_evidence(
            db,
            tenant_id=user.tenant_id,
            student_id=user.id,
            event_id=evidence_event_id,
            event_type="ONBOARDING_RECORDED",
            trace_id=trace_id,
            payload=answers_payload,
            evidence_confidence=0.3,
        )
        if evidence is None:
            # The idempotency-key reservation should already prevent duplicate
            # event_ids; a collision here is a contract violation, not a retry.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="onboarding evidence already recorded",
            )
        profile = project_onboarding(
            db,
            tenant_id=user.tenant_id,
            student_id=user.id,
            source_event_id=evidence_event_id,
            expected_version=body.expected_profile_version,
            answers=answers_payload,
        )
        view = OnboardingSubmissionView(
            evidence_event_id=evidence_event_id,
            profile_version_id=str(profile.id),
            profile_version=profile.version,
            replan_requested=True,
        )
        response_body = view.model_dump(mode="json")
        record_audit(
            db,
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            action="ONBOARDING_SUBMITTED",
            resource_type="profile_version",
            resource_id=str(profile.id),
            trace_id=trace_id,
            detail={"evidence_event_id": evidence_event_id},
        )
        uow.publish(
            event_type="PATH_REPLAN_REQUESTED",
            aggregate_type="profile_version",
            aggregate_id=str(profile.id),
            tenant_id=user.tenant_id,
            trace_id=trace_id,
            payload={
                "evidence_event_id": evidence_event_id,
                "source": "ONBOARDING",
                "weekly_band": body.answers.weekly_band,
            },
        )
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_201_CREATED,
            response_body=response_body,
        )
        uow.commit()
    return view
