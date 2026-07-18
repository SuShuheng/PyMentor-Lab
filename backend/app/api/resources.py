"""Authenticated resource-job create and query API (BE-007)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.command_idempotency import begin_command, scope_for_request
from app.contracts.resources import ResourceJobCreate, ResourceJobView
from app.db import get_db
from app.idempotency import save_response
from app.models import User
from app.rbac import get_current_user
from app.resource_jobs import (
    ResourceJobScopeError,
    assert_resource_job_replay,
    create_resource_job,
    find_idempotent_resource_job,
    get_student_resource_job,
    resource_job_view,
    resource_request_digest,
)
from app.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/resource-jobs", tags=["learning-resources"])


@router.post("", response_model=ResourceJobView, status_code=status.HTTP_202_ACCEPTED)
async def start_resource_job(
    body: ResourceJobCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    request_digest = resource_request_digest(
        body, tenant_id=user.tenant_id, student_id=user.id
    )
    existing = find_idempotent_resource_job(
        db, tenant_id=user.tenant_id, idempotency_key=scope.key
    )
    assert_resource_job_replay(existing, expected_request_digest=request_digest)

    cached = begin_command(db, scope)
    if cached is not None and cached.response_status is not None:
        return JSONResponse(
            content=cached.response_body or {}, status_code=cached.response_status
        )

    trace_id = str(request.state.trace_id)
    try:
        with SqlAlchemyUnitOfWork(accept_session=db) as uow:
            job = existing or create_resource_job(
                db,
                body,
                tenant_id=user.tenant_id,
                student_id=user.id,
                idempotency_key=scope.key,
                request_digest=request_digest,
            )
            view = resource_job_view(db, job)
            response_body = view.model_dump(mode="json")
            if existing is None:
                uow.publish(
                    event_type="RESOURCE_JOB_QUEUED",
                    aggregate_type="resource_job",
                    aggregate_id=str(job.id),
                    tenant_id=user.tenant_id,
                    trace_id=trace_id,
                    payload={
                        "student_id": str(user.id),
                        "course_id": str(job.course_id),
                        "node_id": str(job.node_id),
                        "resource_types": job.requested_types,
                        "source_ids": job.source_ids,
                        "context_digest": job.context_digest,
                    },
                )
            save_response(
                db,
                key=scope.key,
                response_status=status.HTTP_202_ACCEPTED,
                response_body=response_body,
            )
            uow.commit()
    except ResourceJobScopeError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return JSONResponse(content=response_body, status_code=status.HTTP_202_ACCEPTED)


@router.get("/{job_id}", response_model=ResourceJobView)
async def get_resource_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ResourceJobView:
    try:
        job = get_student_resource_job(
            db,
            job_id=job_id,
            tenant_id=user.tenant_id,
            student_id=user.id,
        )
    except ResourceJobScopeError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return resource_job_view(db, job)
