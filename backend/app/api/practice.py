"""Student self-test (practice) loop APIs (BE-023).

Mounts two student-scoped routes:

- ``GET  /api/v1/practice/nodes/{node_id}/questions`` — surface a node's
  ``KnowledgeQuestionTemplate`` rows for self-test. The correct answer is
  never exposed on this endpoint.
- ``POST /api/v1/practice/attempt`` — score the attempt deterministically and
  record a single ``SELF_TEST_ATTEMPTED`` evidence event. Idempotency-Key
  supported.

CONTRACT: the attempt records evidence and NOTHING else. It MUST NOT call
``transition_mastery`` or ``record_assessment_and_decide``. The deterministic
engine consumes self-test evidence later and decides whether to advance
mastery; this API never touches ``MasteryState``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.command_idempotency import begin_command, scope_for_request
from app.contracts.practice import (
    PracticeAttemptRequest,
    PracticeAttemptResponse,
    PracticePerQuestionResult,
    PracticeQuestionKind,
    PracticeQuestionSet,
    PracticeQuestionView,
)
from app.db import get_db
from app.evidence import record_evidence
from app.idempotency import save_response
from app.models import KnowledgeNode, KnowledgeQuestionTemplate, User
from app.rbac import get_current_user

router = APIRouter(prefix="/api/v1/practice", tags=["practice"])

#: Evidence event type recorded for every self-test attempt. Consumed by the
#: deterministic engine downstream; this API never advances mastery on it.
SELF_TEST_EVENT_TYPE = "SELF_TEST_ATTEMPTED"

#: Question kinds surfaced by ``GET /nodes/{id}/questions``. Only
#: ``MULTIPLE_CHOICE`` is machine-scorable by ``POST /attempt`` (it is the only
#: kind whose ``answer_schema`` carries a ``const`` correct option). Returning
#: CODE_* kinds here would let the front-end fetch a question the attempt
#: endpoint must then reject with 422 ("not machine-scorable"), producing a
#: blank practice page for nodes whose only templates are CODE_WRITING (issue 5).
#: The front-end renders an empty list as "暂无选择型自测题，请通过代码实验练习".
MACHINE_SCORABLE_KINDS: frozenset[str] = frozenset({PracticeQuestionKind.MULTIPLE_CHOICE.value})


def _load_node(db: Session, node_id: UUID) -> KnowledgeNode:
    """Load a knowledge node or 404.

    Knowledge nodes are governed (global) catalogue rows; they carry no
    tenant column, so tenant isolation is enforced by authentication alone and
    unknown ids return 404 to avoid leaking existence.
    """

    node = db.get(KnowledgeNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="practice node not found")
    return node


def _question_view(template: KnowledgeQuestionTemplate) -> PracticeQuestionView:
    return PracticeQuestionView(
        id=str(template.id),
        node_id=str(template.node_id),
        kind=PracticeQuestionKind(template.kind),
        prompt_template=template.prompt_template,
        parameter_schema=dict(template.parameter_schema or {}),
    )


def _correct_answer_of(template: KnowledgeQuestionTemplate) -> str | None:
    """Resolve the deterministic correct answer for a template.

    MULTIPLE_CHOICE templates encode the correct option as
    ``answer_schema["const"]``. Templates without a ``const`` are not
    machine-scorable by this API; the attempt endpoint rejects them so the
    score stays deterministic and auditable.
    """

    schema = template.answer_schema or {}
    const = schema.get("const")
    return const if isinstance(const, str) else None


@router.get("/nodes/{node_id}/questions", response_model=PracticeQuestionSet)
async def list_node_questions(
    node_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PracticeQuestionSet:
    del user  # authentication-only dependency; nodes are global catalogue rows
    node = _load_node(db, node_id)
    templates = list(
        db.scalars(
            select(KnowledgeQuestionTemplate)
            .where(KnowledgeQuestionTemplate.node_id == node.id)
            .order_by(KnowledgeQuestionTemplate.created_at, KnowledgeQuestionTemplate.id)
        )
    )
    # Surface only machine-scorable kinds. CODE_* templates belong to the code
    # submission flow; including them here makes the FE fetch a question that
    # ``POST /attempt`` rejects with 422 (issue 5). An empty result is the
    # intended signal that the node has no choice-type self-test.
    scorable = [t for t in templates if t.kind in MACHINE_SCORABLE_KINDS]
    return PracticeQuestionSet(
        node_id=str(node.id),
        course_id=str(node.course_id),
        questions=[_question_view(template) for template in scorable],
    )


@router.post("/attempt", response_model=PracticeAttemptResponse)
async def submit_attempt(
    body: PracticeAttemptRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PracticeAttemptResponse | JSONResponse:
    node = _load_node(db, UUID(body.node_id))

    # Load every template for the node in one pass, then index by id so we can
    # validate each submitted answer belongs to the node and resolve its
    # correct option without leaking existence via distinct error codes.
    templates = list(
        db.scalars(
            select(KnowledgeQuestionTemplate).where(KnowledgeQuestionTemplate.node_id == node.id)
        )
    )
    by_id: dict[UUID, KnowledgeQuestionTemplate] = {template.id: template for template in templates}

    # Validate every answer references a real template on this node.
    for answer in body.answers:
        try:
            question_id = UUID(answer.question_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="question not found in node scope",
            ) from exc
        if question_id not in by_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="question not found in node scope",
            )

    # Idempotency: scope + reserve. A replay returns the cached response body.
    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    cached = begin_command(db, scope)
    if cached is not None and cached.response_status is not None:
        return JSONResponse(
            content=cached.response_body or {},
            status_code=cached.response_status,
        )

    response_body = _score_and_record(
        db,
        request=request,
        user=user,
        node=node,
        body=body,
        by_id=by_id,
    )
    save_response(
        db,
        key=scope.key,
        response_status=status.HTTP_200_OK,
        response_body=response_body,
    )
    db.commit()
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)


def _score_and_record(
    db: Session,
    *,
    request: Request,
    user: User,
    node: KnowledgeNode,
    body: PracticeAttemptRequest,
    by_id: dict[UUID, KnowledgeQuestionTemplate],
) -> dict[str, Any]:
    """Deterministically score the attempt and record one evidence event.

    Does NOT touch ``MasteryState``: the deterministic engine owns mastery and
    consumes the recorded evidence later.
    """

    per_question: list[PracticePerQuestionResult] = []
    correct_count = 0
    for answer in body.answers:
        template = by_id[UUID(answer.question_id)]
        correct_answer = _correct_answer_of(template)
        if correct_answer is None:
            # Non-const templates (e.g. CODE_WRITING) are not machine-scorable
            # here; refuse so the score stays deterministic.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "question is not machine-scorable from a selected answer; "
                    "use the code submission flow instead"
                ),
            )
        is_correct = answer.selected_answer == correct_answer
        if is_correct:
            correct_count += 1
        per_question.append(
            PracticePerQuestionResult(
                question_id=str(template.id),
                correct=is_correct,
                selected_answer=answer.selected_answer,
                correct_answer=correct_answer,
                explanation=None,
            )
        )

    total = len(per_question)
    score = correct_count / total if total else 0.0

    trace_id = str(request.state.trace_id)
    evidence_event_id = f"practice-{uuid4().hex}"
    payload: dict[str, Any] = {
        "score": score,
        "correct_count": correct_count,
        "total_count": total,
        "per_question": [
            {
                "question_id": item.question_id,
                "selected_answer": item.selected_answer,
                "correct_answer": item.correct_answer,
                "correct": item.correct,
            }
            for item in per_question
        ],
    }
    record_evidence(
        db,
        tenant_id=user.tenant_id,
        student_id=user.id,
        event_id=evidence_event_id,
        event_type=SELF_TEST_EVENT_TYPE,
        trace_id=trace_id,
        course_id=node.course_id,
        node_id=node.id,
        payload=payload,
        evidence_confidence=1.0,
    )
    response = PracticeAttemptResponse(
        node_id=str(node.id),
        course_id=str(node.course_id),
        score=score,
        correct_count=correct_count,
        total_count=total,
        per_question=per_question,
        evidence_id=evidence_event_id,
    )
    return response.model_dump(mode="json")


__all__ = ["router"]
