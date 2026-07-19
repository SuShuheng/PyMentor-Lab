"""Student profile query and dispute commands (BE-004)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.command_idempotency import begin_command, scope_for_request
from app.contracts.learning import (
    ProfileDimensionView,
    ProfileDisputeRequest,
    ProfileDisputeView,
    ProfileSnapshot,
)
from app.db import get_db
from app.evidence import record_audit
from app.idempotency import save_response
from app.models import ProfileDimensionScore, ProfileVersion, User
from app.profile_projection import create_profile_dispute
from app.rbac import get_current_user
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
