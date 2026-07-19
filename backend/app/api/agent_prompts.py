"""BE-020 System Admin-only versioned Agent prompt template routes.

V1.0 hardcoded the per-node system prompts inside the Worker. These routes let a
System Admin version, publish, and audit prompt edits per LangGraph node
(orchestrator / profile / path / resource / coach / assessment). At runtime the
Worker reads the single published version per node via ``GET /{node}``.

Integration contract (V1.1):
    Worker fetches the current published prompt with an internal authenticated
    call to ``GET /api/v1/admin/agent-prompts/{node}``. The dry-run endpoint is
    intentionally stubbed (``implemented=False``) until the Worker wires a real
    sandbox execution path; the response shape is stable so the renderer can
    depend on it today.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.command_idempotency import begin_command, scope_for_request
from app.contracts.admin import (
    AGENT_PROMPT_NODES,
    AgentPromptDryRunRequest,
    AgentPromptDryRunView,
    AgentPromptTemplateCreate,
    AgentPromptTemplateHistoryPage,
    AgentPromptTemplateView,
    PageMetadata,
)
from app.db import get_db
from app.evidence import record_audit
from app.idempotency import save_response
from app.models import AgentPromptTemplate, User
from app.rbac import require_system_admin
from app.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/admin/agent-prompts", tags=["admin-agent-prompts"])


def _validate_node(node: str) -> None:
    if node not in AGENT_PROMPT_NODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unknown agent node: {node}",
        )


def _view(template: AgentPromptTemplate) -> AgentPromptTemplateView:
    return AgentPromptTemplateView(
        id=template.id,
        node=template.node,
        version=template.version,
        system_prompt=template.system_prompt,
        published=template.published,
        created_by=template.created_by,
        created_at=template.created_at,
    )


def _cached_response(cached: object) -> JSONResponse | None:
    response_status = getattr(cached, "response_status", None)
    if cached is not None and response_status is not None:
        return JSONResponse(
            content=getattr(cached, "response_body", None) or {},
            status_code=response_status,
        )
    return None


def _scoped_template(
    db: Session, *, tenant_id: UUID, node: str, version: int
) -> AgentPromptTemplate:
    template = db.scalar(
        select(AgentPromptTemplate).where(
            AgentPromptTemplate.tenant_id == tenant_id,
            AgentPromptTemplate.node == node,
            AgentPromptTemplate.version == version,
        )
    )
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")
    return template


def _next_version(db: Session, *, tenant_id: UUID, node: str) -> int:
    current = db.scalar(
        select(func.max(AgentPromptTemplate.version)).where(
            AgentPromptTemplate.tenant_id == tenant_id,
            AgentPromptTemplate.node == node,
        )
    )
    return int(current or 0) + 1


@router.get("/{node}", response_model=AgentPromptTemplateView | None)
async def get_current_prompt(
    node: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> AgentPromptTemplateView | None:
    """Return the current published version for a node, or ``null`` if none.

    This is the endpoint the Worker calls at runtime to read the active system
    prompt for a LangGraph node.
    """

    _validate_node(node)
    template = db.scalar(
        select(AgentPromptTemplate).where(
            AgentPromptTemplate.tenant_id == admin.tenant_id,
            AgentPromptTemplate.node == node,
            AgentPromptTemplate.published.is_(True),
        )
    )
    return None if template is None else _view(template)


@router.get("/{node}/history", response_model=AgentPromptTemplateHistoryPage)
async def get_prompt_history(
    node: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> AgentPromptTemplateHistoryPage:
    _validate_node(node)
    offset = (page - 1) * page_size
    total_items = int(
        db.scalar(
            select(func.count())
            .select_from(AgentPromptTemplate)
            .where(
                AgentPromptTemplate.tenant_id == admin.tenant_id,
                AgentPromptTemplate.node == node,
            )
        )
        or 0
    )
    rows = list(
        db.scalars(
            select(AgentPromptTemplate)
            .where(
                AgentPromptTemplate.tenant_id == admin.tenant_id,
                AgentPromptTemplate.node == node,
            )
            .order_by(AgentPromptTemplate.version.desc(), AgentPromptTemplate.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
    )
    total_pages = 0 if total_items == 0 else (total_items + page_size - 1) // page_size
    return AgentPromptTemplateHistoryPage(
        items=[_view(row) for row in rows],
        page=PageMetadata(
            number=page,
            size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        ),
    )


@router.post("/{node}", response_model=AgentPromptTemplateView, status_code=status.HTTP_201_CREATED)
async def create_prompt_version(
    node: str,
    body: AgentPromptTemplateCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> JSONResponse:
    """Create a new draft version for a node (monotonic per tenant+node)."""

    _validate_node(node)
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cached_response(begin_command(db, scope))
    if cached_response is not None:
        return cached_response
    trace_id = str(request.state.trace_id)
    version = _next_version(db, tenant_id=admin.tenant_id, node=node)
    template = AgentPromptTemplate(
        id=uuid4(),
        tenant_id=admin.tenant_id,
        node=node,
        version=version,
        system_prompt=body.system_prompt,
        published=False,
        created_by=admin.id,
    )
    try:
        with SqlAlchemyUnitOfWork(accept_session=db) as uow:
            db.add(template)
            db.flush()
            response_body = _view(template).model_dump(mode="json")
            record_audit(
                db,
                tenant_id=admin.tenant_id,
                actor_user_id=admin.id,
                action="AGENT_PROMPT_VERSION_CREATED",
                resource_type="agent_prompt_template",
                resource_id=str(template.id),
                trace_id=trace_id,
                detail={"node": node, "version": version},
            )
            uow.publish(
                event_type="AGENT_PROMPT_VERSION_CREATED",
                aggregate_type="agent_prompt_template",
                aggregate_id=str(template.id),
                tenant_id=admin.tenant_id,
                trace_id=trace_id,
                payload={"node": node, "version": version},
            )
            save_response(
                db,
                key=scope.key,
                response_status=status.HTTP_201_CREATED,
                response_body=response_body,
            )
            uow.commit()
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prompt version already exists",
        ) from error
    return JSONResponse(content=response_body, status_code=status.HTTP_201_CREATED)


@router.post("/{node}/{version}/publish", response_model=AgentPromptTemplateView)
async def publish_prompt_version(
    node: str,
    version: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> JSONResponse:
    """Publish a specific version; atomically unpublish the others for the node.

    Every publish writes an ``AGENT_PROMPT_PUBLISHED`` audit event so prompt
    edits are traceable to an actor and trace.
    """

    _validate_node(node)
    template = _scoped_template(db, tenant_id=admin.tenant_id, node=node, version=version)
    trace_id = str(request.state.trace_id)
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        # Unpublish every other version for this node in the same transaction.
        db.execute(
            update(AgentPromptTemplate)
            .where(
                AgentPromptTemplate.tenant_id == admin.tenant_id,
                AgentPromptTemplate.node == node,
                AgentPromptTemplate.id != template.id,
                AgentPromptTemplate.published.is_(True),
            )
            .values(published=False)
        )
        template.published = True
        db.flush()
        response_body = _view(template).model_dump(mode="json")
        record_audit(
            db,
            tenant_id=admin.tenant_id,
            actor_user_id=admin.id,
            action="AGENT_PROMPT_PUBLISHED",
            resource_type="agent_prompt_template",
            resource_id=str(template.id),
            trace_id=trace_id,
            detail={"node": node, "version": version},
        )
        uow.publish(
            event_type="AGENT_PROMPT_PUBLISHED",
            aggregate_type="agent_prompt_template",
            aggregate_id=str(template.id),
            tenant_id=admin.tenant_id,
            trace_id=trace_id,
            payload={"node": node, "version": version},
        )
        uow.commit()
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)


@router.post("/{node}/dry-run", response_model=AgentPromptDryRunView)
async def dry_run_prompt(
    node: str,
    body: AgentPromptDryRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> AgentPromptDryRunView:
    """Honest V1.1 stub: returns the stable contract without invoking the Worker.

    The Worker sandboxed execution path is intentionally deferred. The response
    shape is final so the renderer can integrate against it today; ``implemented``
    flips to ``True`` once the Worker wires a real dry-run call.
    """

    _validate_node(node)
    return AgentPromptDryRunView(
        node=node,
        implemented=False,
        note="Worker integration pending: dry-run execution is not wired in V1.1.",
    )
