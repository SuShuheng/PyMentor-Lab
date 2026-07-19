"""BE-027 minimal course CMS API.

V1.0 seeds the knowledge base from a frozen JSON file with no editing
surface. This router gives Course Admin / System Admin a minimal, audited
way to edit knowledge nodes and question templates. The CMS never bypasses
the governed asset contracts: every edit is validated by reusing
``knowledge_assets.validate_course_document`` and every successful write
records an ``AuditEvent``.

Versioning decision (documented per the BE-027 design note)
-----------------------------------------------------------
A full staging-table version-control flow is out of scope for V1.1. Instead:

* ``PUT`` validates + applies + audits atomically. The handler rebuilds a
  synthetic full course document by replacing the single edited asset with
  its proposed shape, runs the doc-level validator (cycle check, source
  whitelist, reference integrity, schema), and only on a clean report
  applies the change to the published row in the same transaction and
  writes the ``AuditEvent``. The row's ``content_version`` is advanced so
  the edit is never silent.
* ``POST publish`` is the explicit, audit-confirmed commit step. Because
  the PUT already applied the edit atomically, publish re-affirms that the
  current row version is the live published one and records a separate
  ``AuditEvent`` with a ``*_PUBLISHED`` action. This keeps the contract
  that "publishes are audited" without inventing a staging table the
  migration / model layer does not yet carry.

A staging table + diff/version graph is deferred to a later slice.

Audit detail shape
------------------
Every audit ``detail`` carries ``source="CMS"``, the editor's
``actor_user_id`` (column, not detail), and a redacted SHA-256 ``digest`` of
the proposed payload — never the raw payload, which may contain prompt text
the editor has not yet cleared for log review.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.command_idempotency import begin_command, scope_for_request
from app.contracts.cms import (
    CmsNodeListItem,
    CmsNodePage,
    CmsNodeUpdate,
    CmsNodeView,
    CmsPageMetadata,
    CmsPublishRequest,
    CmsPublishView,
    CmsQuestionUpdate,
    CmsQuestionView,
)
from app.db import get_db
from app.evidence import record_audit
from app.idempotency import save_response
from app.knowledge_assets import validate_course_document
from app.models import (
    CourseCatalog,
    CourseChapter,
    KnowledgeNode,
    KnowledgeQuestionTemplate,
    User,
)
from app.rbac import require_course_admin
from app.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/admin/cms", tags=["cms"])

_AUDIT_SOURCE = "CMS"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _bump_patch(version: str) -> str:
    """Advance the patch component of a semantic version (``1.0.0`` -> ``1.0.1``).

    The CMS advances patch versions only; minor/major bumps are out of scope
    for an in-place editorial fix.
    """

    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        # Fall back to a safe default rather than corrupting the column.
        return version
    major, minor, patch = (int(part) for part in parts)
    return f"{major}.{minor}.{patch + 1}"


def _payload_digest(payload: Mapping[str, Any]) -> str:
    """Redacted SHA-256 of the proposed edit payload (no raw values logged)."""

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _node_view(node: KnowledgeNode) -> CmsNodeView:
    return CmsNodeView(
        node_id=node.id,
        course_id=node.course_id,
        chapter_id=node.chapter_id,
        title=node.title,
        learning_objectives=list(node.learning_objectives),
        prerequisites=[UUID(value) for value in node.prerequisites],
        misconceptions=list(node.misconceptions),
        examples=list(node.examples),
        diagnostic_items=[UUID(value) for value in node.diagnostic_items],
        practice_templates=[UUID(value) for value in node.practice_templates],
        mastery_policy_id=node.mastery_policy_id,
        source_ids=[UUID(value) for value in node.source_ids],
        content_version=node.content_version,
    )


def _question_view(question: KnowledgeQuestionTemplate) -> CmsQuestionView:
    return CmsQuestionView(
        question_id=question.id,
        node_id=question.node_id,
        kind=question.kind,
        prompt_template=question.prompt_template,
        parameter_schema=dict(question.parameter_schema),
        answer_schema=dict(question.answer_schema),
        test_case_ids=[UUID(value) for value in question.test_case_ids],
        source_ids=[UUID(value) for value in question.source_ids],
        content_version=question.content_version,
    )


def _load_course_document(db: Session, course_id: UUID) -> dict[str, Any]:
    """Rebuild a synthetic ``CourseAssetBundle`` document from current rows.

    The validator operates on the canonical JSON shape (the same one
    ``knowledge_seed`` consumes), so to validate a single node edit we
    rebuild that shape from the live published rows and let the caller
    splice in the proposed change before validation.
    """

    course = db.get(CourseCatalog, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course not found")

    nodes = list(db.scalars(select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)))
    questions = list(
        db.scalars(
            select(KnowledgeQuestionTemplate).where(
                KnowledgeQuestionTemplate.node_id.in_([n.id for n in nodes])
            )
        )
        if nodes
        else []
    )

    # The validator only inspects fields the bundle contract carries. We do
    # not need every governing table (sources/policies/chapters/error patterns
    # are unchanged by a node/question edit) — we load only what the validator
    # needs to confirm the edited asset still passes reference integrity.
    from app.models import (
        CourseChapter,
        KnowledgeErrorPattern,
        KnowledgeMasteryPolicy,
        KnowledgeSource,
        KnowledgeTestCase,
    )

    chapters = list(db.scalars(select(CourseChapter).where(CourseChapter.course_id == course_id)))
    source_ids_seen: set[UUID] = set()
    for node in nodes:
        source_ids_seen.update(UUID(s) for s in node.source_ids)
    for question in questions:
        source_ids_seen.update(UUID(s) for s in question.source_ids)
    sources = (
        list(db.scalars(select(KnowledgeSource).where(KnowledgeSource.id.in_(source_ids_seen))))
        if source_ids_seen
        else []
    )
    policy_ids = {n.mastery_policy_id for n in nodes}
    policies = (
        list(
            db.scalars(
                select(KnowledgeMasteryPolicy).where(KnowledgeMasteryPolicy.id.in_(policy_ids))
            )
        )
        if policy_ids
        else []
    )
    test_ids: set[UUID] = set()
    for question in questions:
        test_ids.update(UUID(t) for t in question.test_case_ids)
    test_cases = (
        list(db.scalars(select(KnowledgeTestCase).where(KnowledgeTestCase.id.in_(test_ids))))
        if test_ids
        else []
    )
    error_patterns = list(db.scalars(select(KnowledgeErrorPattern)))

    document: dict[str, Any] = {
        "schema_version": course.schema_version,
        "content_version": course.content_version,
        "course": {
            "course_id": str(course.id),
            "slug": course.slug,
            "title": course.title,
            "audience": course.audience,
            "language": course.language,
            "chapter_ids": list(course.chapter_ids),
            "required_chapter_count": len(course.chapter_ids),
            "minimum_node_count": 1,
            "required_deep_unit_count": len(course.deep_unit_node_ids),
            "deep_unit_node_ids": list(course.deep_unit_node_ids),
            "version": course.content_version,
        },
        "chapters": [
            {
                "chapter_id": str(c.id),
                "course_id": str(c.course_id),
                "order": c.sequence,
                "title": c.title,
                "learning_objectives": list(c.learning_objectives),
                "node_ids": [str(n.id) for n in nodes if n.chapter_id == c.id],
                "version": c.content_version,
            }
            for c in chapters
        ],
        "nodes": [
            {
                "node_id": str(n.id),
                "title": n.title,
                "chapter_id": str(n.chapter_id),
                "learning_objectives": list(n.learning_objectives),
                "prerequisites": list(n.prerequisites),
                "misconceptions": list(n.misconceptions),
                "examples": list(n.examples),
                "diagnostic_items": list(n.diagnostic_items),
                "practice_templates": list(n.practice_templates),
                "mastery_policy_id": str(n.mastery_policy_id),
                "source_ids": list(n.source_ids),
                "version": n.content_version,
            }
            for n in nodes
        ],
        "sources": [
            {
                "source_id": str(s.id),
                "title": s.title,
                "url": s.url,
                "publisher": s.publisher,
                "content_scope": s.content_scope,
                "version": s.content_version,
            }
            for s in sources
        ],
        "error_patterns": [
            {
                "error_id": str(p.id),
                "title": p.title,
                "node_ids": list(p.node_ids),
                "symptom": p.symptom,
                "misconception": p.misconception,
                "diagnosis_prompts": list(p.diagnosis_prompts),
                "remediation": list(p.remediation),
                "source_ids": list(p.source_ids),
                "version": p.content_version,
            }
            for p in error_patterns
        ],
        "question_templates": [
            {
                "question_id": str(q.id),
                "node_id": str(q.node_id),
                "kind": q.kind,
                "prompt_template": q.prompt_template,
                "parameter_schema": dict(q.parameter_schema),
                "answer_schema": dict(q.answer_schema),
                "test_case_ids": list(q.test_case_ids),
                "source_ids": list(q.source_ids),
                "version": q.content_version,
            }
            for q in questions
        ],
        "test_cases": [
            {
                "test_id": str(t.id),
                "node_id": str(t.node_id),
                "kind": t.kind,
                "input": t.input,
                "expected": t.expected,
                "hidden": t.hidden,
                "timeout_ms": t.timeout_ms,
                "version": t.content_version,
            }
            for t in test_cases
        ],
        "mastery_policies": [
            {
                "policy_id": str(p.id),
                "name": p.name,
                "pass_threshold": p.pass_threshold,
                "stable_attempts": p.stable_attempts,
                "max_support_level": p.max_support_level,
                "min_transfer_score": p.min_transfer_score,
                "review_intervals_days": list(p.review_intervals_days),
                "version": p.content_version,
            }
            for p in policies
        ],
    }
    return document


def _validation_error(findings: list[Any]) -> HTTPException:
    detail = "; ".join(f"{f.code}:{f.path}" for f in findings[:5])
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"course asset validation failed: {detail}",
    )


def _cache_response(cached: Any) -> JSONResponse | None:
    response_status = getattr(cached, "response_status", None)
    if cached is not None and response_status is not None:
        return JSONResponse(
            content=getattr(cached, "response_body", None) or {},
            status_code=response_status,
        )
    return None


def _load_node_or_404(db: Session, node_id: UUID) -> KnowledgeNode:
    node = db.get(KnowledgeNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="node not found")
    return node


def _load_question_or_404(db: Session, question_id: UUID) -> KnowledgeQuestionTemplate:
    question = db.get(KnowledgeQuestionTemplate, question_id)
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="question template not found"
        )
    return question


# --------------------------------------------------------------------------- #
# Node list (BE-027 V1.1: paginated browser surface)
# --------------------------------------------------------------------------- #
@router.get("/nodes", response_model=CmsNodePage)
async def list_nodes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_course_admin),
) -> CmsNodePage:
    """Paginated, optionally filtered list of knowledge nodes.

    Nodes are ordered by chapter ``sequence`` then ``KnowledgeNode.id`` (the
    same governed ordering used by ``profiles._first_nodes_of_course``) so the
    CMS browser mirrors the course's pedagogical order. ``q`` is a substring
    match on node title (case-insensitive ``ilike``); the ``min_length=1``
    constraint on the query param rejects empty-string searches up front.
    """

    base = (
        select(
            KnowledgeNode,
            CourseChapter.title.label("chapter_title"),
        )
        .join(CourseChapter, CourseChapter.id == KnowledgeNode.chapter_id)
    )
    if q:
        base = base.where(KnowledgeNode.title.ilike(f"%{q}%"))

    total_items = db.scalar(
        select(func.count())
        .select_from(base.subquery())
    ) or 0

    rows = list(
        db.execute(
            base.order_by(CourseChapter.sequence, KnowledgeNode.id)
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
    )

    items = [
        CmsNodeListItem(
            node_id=node.id,
            course_id=node.course_id,
            chapter_id=node.chapter_id,
            chapter_title=chapter_title or "",
            title=node.title,
            content_version=node.content_version,
        )
        for node, chapter_title in rows
    ]
    total_pages = (total_items + page_size - 1) // page_size if total_items else 0
    return CmsNodePage(
        items=items,
        page=CmsPageMetadata(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        ),
    )


# --------------------------------------------------------------------------- #
# Node endpoints
# --------------------------------------------------------------------------- #
@router.get("/nodes/{node_id}", response_model=CmsNodeView)
async def get_node(
    node_id: UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_course_admin),
) -> CmsNodeView:
    """Read a node's full editable shape."""

    return _node_view(_load_node_or_404(db, node_id))


@router.put("/nodes/{node_id}", response_model=CmsNodeView)
async def put_node(
    node_id: UUID,
    body: CmsNodeUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> JSONResponse:
    """Validate + apply + audit a node edit atomically.

    The proposed shape is merged onto the current node, spliced into a
    synthetic full-course document, and run through
    ``validate_course_document``. On a clean report the row is updated, its
    ``content_version`` is advanced, and an ``AuditEvent`` is recorded —
    all in one transaction. On any validation finding the row is untouched
    and no audit row is written.
    """

    node = _load_node_or_404(db, node_id)
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cache_response(begin_command(db, scope))
    if cached_response is not None:
        return cached_response

    proposed_payload: dict[str, Any] = body.model_dump(exclude_unset=True)
    if not proposed_payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="no fields supplied to update",
        )

    # Merge proposed fields onto the current node snapshot for validation.
    proposed_node = {
        "node_id": str(node.id),
        "title": proposed_payload.get("title", node.title),
        "chapter_id": str(node.chapter_id),
        "learning_objectives": proposed_payload.get(
            "learning_objectives", list(node.learning_objectives)
        ),
        "prerequisites": [
            str(value) for value in proposed_payload.get("prerequisites", node.prerequisites)
        ],
        "misconceptions": proposed_payload.get("misconceptions", list(node.misconceptions)),
        "examples": proposed_payload.get("examples", list(node.examples)),
        "diagnostic_items": [
            str(value) for value in proposed_payload.get("diagnostic_items", node.diagnostic_items)
        ],
        "practice_templates": [
            str(value)
            for value in proposed_payload.get("practice_templates", node.practice_templates)
        ],
        "mastery_policy_id": str(node.mastery_policy_id),
        "source_ids": [str(value) for value in proposed_payload.get("source_ids", node.source_ids)],
        "version": node.content_version,
    }

    document = _load_course_document(db, node.course_id)
    for index, entry in enumerate(document["nodes"]):
        if entry["node_id"] == str(node.id):
            document["nodes"][index] = proposed_node
            break

    report = validate_course_document(document)
    if not report.valid:
        raise _validation_error(report.findings)

    new_version = _bump_patch(node.content_version)
    response_view = _apply_node_edit(db, node, proposed_payload, new_version)
    response_body = response_view.model_dump(mode="json")
    _record_cms_audit(
        db,
        action="CMS_NODE_UPDATED",
        resource_type="knowledge_node",
        resource_id=str(node.id),
        admin=admin,
        trace_id=str(request.state.trace_id),
        payload=proposed_payload,
        new_version=new_version,
    )
    save_response(
        db,
        key=scope.key,
        response_status=status.HTTP_200_OK,
        response_body=response_body,
    )
    db.commit()
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)


def _apply_node_edit(
    db: Session,
    node: KnowledgeNode,
    payload: dict[str, Any],
    new_version: str,
) -> CmsNodeView:
    """Apply the validated patch to the row (no further validation here)."""

    if "title" in payload:
        node.title = payload["title"]
    if "learning_objectives" in payload:
        node.learning_objectives = list(payload["learning_objectives"])
    if "prerequisites" in payload:
        node.prerequisites = [str(v) for v in payload["prerequisites"]]
    if "misconceptions" in payload:
        node.misconceptions = list(payload["misconceptions"])
    if "examples" in payload:
        node.examples = list(payload["examples"])
    if "diagnostic_items" in payload:
        node.diagnostic_items = [str(v) for v in payload["diagnostic_items"]]
    if "practice_templates" in payload:
        node.practice_templates = [str(v) for v in payload["practice_templates"]]
    if "source_ids" in payload:
        node.source_ids = [str(v) for v in payload["source_ids"]]
    node.content_version = new_version
    db.flush()
    return _node_view(node)


@router.post("/nodes/{node_id}/publish", response_model=CmsPublishView)
async def publish_node(
    node_id: UUID,
    body: CmsPublishRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> JSONResponse:
    """Audit-confirmed commit step for a node.

    The PUT already applied the edit atomically; this endpoint records the
    explicit publish decision so reviewers can distinguish "edited" from
    "released to learners".
    """

    node = _load_node_or_404(db, node_id)
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cache_response(begin_command(db, scope))
    if cached_response is not None:
        return cached_response

    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        record_audit(
            db,
            tenant_id=admin.tenant_id,
            actor_user_id=admin.id,
            action="CMS_NODE_PUBLISHED",
            resource_type="knowledge_node",
            resource_id=str(node.id),
            trace_id=str(request.state.trace_id),
            detail={
                "source": _AUDIT_SOURCE,
                "content_version": node.content_version,
                "notes": body.notes,
            },
        )
        response_body = CmsPublishView(
            node_id=node.id,
            published=True,
            content_version=node.content_version,
            actor_user_id=admin.id,
        ).model_dump(mode="json")
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_200_OK,
            response_body=response_body,
        )
        uow.commit()
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)


# --------------------------------------------------------------------------- #
# Question template endpoints
# --------------------------------------------------------------------------- #
@router.put("/question_templates/{question_id}", response_model=CmsQuestionView)
async def put_question(
    question_id: UUID,
    body: CmsQuestionUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> JSONResponse:
    """Validate + apply + audit a question template edit atomically."""

    question = _load_question_or_404(db, question_id)
    node = _load_node_or_404(db, question.node_id)
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cache_response(begin_command(db, scope))
    if cached_response is not None:
        return cached_response

    proposed_payload: dict[str, Any] = body.model_dump(exclude_unset=True)
    if not proposed_payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="no fields supplied to update",
        )

    proposed_question = {
        "question_id": str(question.id),
        "node_id": str(question.node_id),
        "kind": question.kind,
        "prompt_template": proposed_payload.get("prompt_template", question.prompt_template),
        "parameter_schema": proposed_payload.get(
            "parameter_schema", dict(question.parameter_schema)
        ),
        "answer_schema": proposed_payload.get("answer_schema", dict(question.answer_schema)),
        "test_case_ids": [
            str(value) for value in proposed_payload.get("test_case_ids", question.test_case_ids)
        ],
        "source_ids": [
            str(value) for value in proposed_payload.get("source_ids", question.source_ids)
        ],
        "version": question.content_version,
    }

    document = _load_course_document(db, node.course_id)
    for index, entry in enumerate(document["question_templates"]):
        if entry["question_id"] == str(question.id):
            document["question_templates"][index] = proposed_question
            break

    report = validate_course_document(document)
    if not report.valid:
        raise _validation_error(report.findings)

    new_version = _bump_patch(question.content_version)
    response_view = _apply_question_edit(db, question, proposed_payload, new_version)
    response_body = response_view.model_dump(mode="json")
    _record_cms_audit(
        db,
        action="CMS_QUESTION_UPDATED",
        resource_type="knowledge_question_template",
        resource_id=str(question.id),
        admin=admin,
        trace_id=str(request.state.trace_id),
        payload=proposed_payload,
        new_version=new_version,
    )
    save_response(
        db,
        key=scope.key,
        response_status=status.HTTP_200_OK,
        response_body=response_body,
    )
    db.commit()
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)


def _apply_question_edit(
    db: Session,
    question: KnowledgeQuestionTemplate,
    payload: dict[str, Any],
    new_version: str,
) -> CmsQuestionView:
    if "prompt_template" in payload:
        question.prompt_template = payload["prompt_template"]
    if "parameter_schema" in payload:
        question.parameter_schema = dict(payload["parameter_schema"])
    if "answer_schema" in payload:
        question.answer_schema = dict(payload["answer_schema"])
    if "test_case_ids" in payload:
        question.test_case_ids = [str(v) for v in payload["test_case_ids"]]
    if "source_ids" in payload:
        question.source_ids = [str(v) for v in payload["source_ids"]]
    question.content_version = new_version
    db.flush()
    return _question_view(question)


@router.post("/question_templates/{question_id}/publish", response_model=CmsPublishView)
async def publish_question(
    question_id: UUID,
    body: CmsPublishRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> JSONResponse:
    """Audit-confirmed commit step for a question template."""

    question = _load_question_or_404(db, question_id)
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cache_response(begin_command(db, scope))
    if cached_response is not None:
        return cached_response

    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        record_audit(
            db,
            tenant_id=admin.tenant_id,
            actor_user_id=admin.id,
            action="CMS_QUESTION_PUBLISHED",
            resource_type="knowledge_question_template",
            resource_id=str(question.id),
            trace_id=str(request.state.trace_id),
            detail={
                "source": _AUDIT_SOURCE,
                "content_version": question.content_version,
                "notes": body.notes,
            },
        )
        response_body = CmsPublishView(
            question_id=question.id,
            published=True,
            content_version=question.content_version,
            actor_user_id=admin.id,
        ).model_dump(mode="json")
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_200_OK,
            response_body=response_body,
        )
        uow.commit()
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)


# --------------------------------------------------------------------------- #
# Shared audit writer for PUT (write + audit in the same transaction)
# --------------------------------------------------------------------------- #
def _record_cms_audit(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    admin: User,
    trace_id: str,
    payload: Mapping[str, Any],
    new_version: str,
) -> None:
    """Record an ``AuditEvent`` for a validated CMS edit.

    The detail carries a redacted digest of the proposed payload (not the
    raw payload), the new ``content_version``, and the ``CMS`` source marker.
    """

    record_audit(
        db,
        tenant_id=admin.tenant_id,
        actor_user_id=admin.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        trace_id=trace_id,
        detail={
            "source": _AUDIT_SOURCE,
            "digest": _payload_digest(payload),
            "content_version": new_version,
        },
    )
    db.flush()
