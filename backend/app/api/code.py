"""Student code run, submission, cancellation, and query APIs (BE-005 Task 8).

Mounts five student-scoped routes:

- ``POST /api/v1/code/runs`` — execute visible cases (RUN) or with trace (TRACE).
- ``POST /api/v1/code/submissions`` — execute visible + hidden phases (SUBMIT).
- ``GET  /api/v1/code/runs/{run_id}`` — fetch a student-scoped run view.
- ``POST /api/v1/code/runs/{run_id}/cancel`` — cancel a non-terminal run.
- ``POST /api/v1/tasks/{task_instance_id}/hints`` lives in ``api/hints.py``.

Each write command validates auth, tenant/student scope, optimistic version,
and scoped idempotency before invoking the three-transaction orchestrator.
Responses never expose source code, hidden IDs, expected hidden values, or
container/host details.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.code_execution import CodeCommand, cancel_code_run, execute_code_command
from app.command_idempotency import IdempotencyInProgressError, begin_command, scope_for_request
from app.config import get_settings
from app.contracts.sandbox import (
    CodeRunMode,
    CodeRunRequest,
    CodeRunStatus,
    CodeRunView,
    CodeSubmissionRequest,
)
from app.db import SessionLocal, get_db
from app.idempotency import IdempotencyScopeConflictError, save_response
from app.models import CodeRun, IdempotencyKey, TaskInstance, TaskInstanceStatus, User
from app.rbac import get_current_user
from app.sandbox_client import SandboxClient, SandboxClientConfig

router = APIRouter(prefix="/api/v1/code", tags=["code-evidence"])


def _now() -> datetime:
    return datetime.now(UTC)


def _settings() -> Any:
    return get_settings()


def get_sandbox_client() -> SandboxClient:
    """FastAPI dependency: build a SandboxClient from current settings.

    Tests override this with a fake client. The shared secret must be
    configured in any non-test environment; a missing secret surfaces as a
    platform fault when the first execution is attempted.
    """

    settings = _settings()
    secret = settings.sandbox_secret.encode("utf-8") if settings.sandbox_secret else b""
    config = SandboxClientConfig(
        base_url=settings.sandbox_supervisor_url,
        shared_secret=secret,
        timeout_seconds=float(settings.sandbox_request_timeout_seconds),
    )
    return SandboxClient(config)


def get_session_factory() -> Any:
    """FastAPI dependency returning the orchestration session factory.

    Tests override this to bind the orchestrator to the test's savepoint-bound
    session so the three-transaction flow is visible to assertions.
    """

    return SessionLocal


def _load_active_task(
    db: Session,
    *,
    task_instance_id: str,
    user: User,
    expected_task_version: int,
) -> TaskInstance:
    instance = db.scalar(
        select(TaskInstance).where(
            TaskInstance.id == task_instance_id,
            TaskInstance.tenant_id == user.tenant_id,
            TaskInstance.student_id == user.id,
        )
    )
    if instance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if instance.status != TaskInstanceStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"task is {instance.status.value.lower()}",
        )
    if instance.version != expected_task_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"expected task version {expected_task_version}, actual {instance.version}",
        )
    return instance


def _fetch_idempotency(db: Session, key: str) -> IdempotencyKey | None:
    """Re-fetch the idempotency reservation created by ``begin_command``."""

    return db.scalar(select(IdempotencyKey).where(IdempotencyKey.key == key))


def _execute_command(
    request: Request,
    db: Session,
    user: User,
    sandbox: SandboxClient,
    session_factory: Any,
    *,
    body: CodeRunRequest | CodeSubmissionRequest,
    mode: CodeRunMode,
) -> JSONResponse:
    """Shared run/submission flow: scope, idempotency, orchestrate, persist."""

    instance = _load_active_task(
        db,
        task_instance_id=body.task_instance_id,
        user=user,
        expected_task_version=body.expected_task_version,
    )
    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    cached = begin_command(db, scope)
    if cached is not None and cached.response_status is not None:
        return JSONResponse(
            content=cached.response_body or {},
            status_code=cached.response_status,
        )
    if cached is not None and cached.response_status is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotent command is still in progress",
        )
    db.flush()
    # begin_command returned None for a freshly created reservation; re-fetch it
    # so the orchestrator can link the run and complete the response.
    idempotency = cached if cached is not None else _fetch_idempotency(db, scope.key)
    if idempotency is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotent command reservation was not persisted",
        )

    trace_enabled = getattr(body, "trace_enabled", False) or mode == CodeRunMode.TRACE
    command = CodeCommand(
        task=instance,
        source_code=body.source_code,
        mode=mode,
        idempotency=idempotency,
        expected_task_version=body.expected_task_version,
        trace_enabled=trace_enabled,
        trace_id=str(request.state.trace_id),
    )
    view = execute_code_command(command, sandbox=sandbox, session_factory=session_factory)
    response_body = CodeRunView.model_validate(view).model_dump(mode="json")
    save_response(
        db,
        key=scope.key,
        response_status=status.HTTP_200_OK,
        response_body=response_body,
    )
    db.commit()
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)


@router.post("/runs", response_model=CodeRunView)
async def create_run(
    body: CodeRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    sandbox: SandboxClient = Depends(get_sandbox_client),
    session_factory: Any = Depends(get_session_factory),
) -> JSONResponse:
    try:
        return _execute_command(
            request, db, user, sandbox, session_factory, body=body, mode=CodeRunMode.RUN
        )
    except IdempotencyScopeConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotency key scope conflict",
        ) from exc
    except IdempotencyInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotent command is still in progress",
        ) from exc


@router.post("/submissions", response_model=CodeRunView)
async def create_submission(
    body: CodeSubmissionRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    sandbox: SandboxClient = Depends(get_sandbox_client),
    session_factory: Any = Depends(get_session_factory),
) -> JSONResponse:
    try:
        return _execute_command(
            request, db, user, sandbox, session_factory, body=body, mode=CodeRunMode.SUBMIT
        )
    except IdempotencyScopeConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotency key scope conflict",
        ) from exc
    except IdempotencyInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotent command is still in progress",
        ) from exc


@router.get("/runs/{run_id}", response_model=CodeRunView)
async def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    run = db.scalar(
        select(CodeRun).where(
            CodeRun.run_id == run_id,
            CodeRun.tenant_id == user.tenant_id,
            CodeRun.student_id == user.id,
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    view = _run_view(run)
    return JSONResponse(content=view, status_code=status.HTTP_200_OK)


@router.post("/runs/{run_id}/cancel", response_model=CodeRunView)
async def cancel_run(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    sandbox: SandboxClient = Depends(get_sandbox_client),
    session_factory: Any = Depends(get_session_factory),
) -> JSONResponse:
    run = db.scalar(
        select(CodeRun)
        .where(
            CodeRun.run_id == run_id,
            CodeRun.tenant_id == user.tenant_id,
            CodeRun.student_id == user.id,
        )
        .with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    if run.status in {
        CodeRunStatus.COMPLETED,
        CodeRunStatus.USER_ERROR,
        CodeRunStatus.PLATFORM_ERROR,
        CodeRunStatus.TIMEOUT,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"run is terminal: {run.status.value}",
        )
    if run.status == CodeRunStatus.CANCELLED:
        return JSONResponse(content=_run_view(run), status_code=status.HTTP_200_OK)

    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    cached = begin_command(db, scope)
    if cached is not None and cached.response_status is not None:
        return JSONResponse(
            content=cached.response_body or {},
            status_code=cached.response_status,
        )
    db.flush()
    view = cancel_code_run(
        run,
        sandbox=sandbox,
        session_factory=session_factory,
        trace_id=str(request.state.trace_id),
    )
    response_body = CodeRunView.model_validate(view).model_dump(mode="json")
    save_response(
        db,
        key=scope.key,
        response_status=status.HTTP_200_OK,
        response_body=response_body,
    )
    db.commit()
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)


def _run_view(run: CodeRun) -> dict[str, Any]:
    """Build a CodeRunView dict (no source/hidden policy/host paths)."""

    from sqlalchemy.orm import object_session

    from app.models import CodeRevision

    session = object_session(run)
    revision = session.get(CodeRevision, run.revision_id) if session else None
    revision_view = {
        "id": str(run.revision_id),
        "sequence": revision.sequence if revision else 1,
        "source_digest": revision.source_digest if revision else "0" * 64,
        "created_at": (revision.created_at if revision else run.requested_at).isoformat(),
    }
    return {
        "run_id": run.run_id,
        "task_instance_id": str(run.task_instance_id),
        "mode": run.mode.value,
        "status": run.status.value,
        "version": run.version,
        "revision": revision_view,
        "result": run.result,
        "evidence_event_id": run.evidence_event_id,
        "requested_at": run.requested_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


__all__ = ["router"]
