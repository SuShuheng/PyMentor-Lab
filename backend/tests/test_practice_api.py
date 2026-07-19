"""Student self-test (practice) API integration tests (BE-023).

The practice loop is: ``GET /api/v1/practice/nodes/{node_id}/questions`` →
``POST /api/v1/practice/attempt`` → score + per-question feedback. The attempt
records evidence but MUST NOT auto-advance mastery (CONTRACT: only the
deterministic engine decides mastery).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import create_app
from app.models import (
    CourseCatalog,
    EvidenceEvent,
    KnowledgeMasteryPolicy,
    KnowledgeNode,
    KnowledgeQuestionTemplate,
    MasteryState,
    MasteryStatus,
    User,
    UserStatus,
)
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant

# Governed course id reused across the learning loop (matches conftest seed).
COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def student_auth(client: TestClient, db_session: Session) -> tuple[User, str]:
    tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
    db_session.flush()
    password = "ValidPass1!"
    user = create_student_user(
        db_session,
        tenant_id=tenant.id,
        email=f"practice-{uuid4().hex}@example.com",
        password_hash=hash_password(password),
    )
    user.status = UserStatus.ACTIVE
    db_session.flush()
    response = client.post("/api/v1/auth/login", json={"email": user.email, "password": password})
    assert response.status_code == 200, response.text
    return user, response.json()["access_token"]


def _headers(token: str, key: str | None = None, trace_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    if trace_id is not None:
        headers["x-trace-id"] = trace_id
    return headers


def _seed_node_with_questions(
    db_session: Session,
) -> tuple[KnowledgeNode, list[KnowledgeQuestionTemplate]]:
    """Seed a governed node with three MULTIPLE_CHOICE templates.

    The templates use ``answer_schema`` with ``const`` so the correct option is
    deterministic and machine-comparable (mirrors the seeded V1.0 shape).
    """

    from app.models import CourseChapter

    course = db_session.get(CourseCatalog, COURSE_ID)
    assert course is not None, "canonical course must be seeded by conftest"
    chapter = db_session.scalar(select(CourseChapter).where(CourseChapter.course_id == COURSE_ID))
    assert chapter is not None, "canonical course must have chapters seeded"

    policy = KnowledgeMasteryPolicy(
        id=uuid4(),
        name=f"practice-policy-{uuid4().hex}",
        pass_threshold=0.7,
        stable_attempts=2,
        max_support_level=1,
        min_transfer_score=0.6,
        review_intervals_days=[7, 30],
        content_version=course.content_version,
    )
    db_session.add(policy)
    db_session.flush()

    node = KnowledgeNode(
        id=uuid4(),
        course_id=COURSE_ID,
        chapter_id=chapter.id,
        title="Practice self-test node",
        learning_objectives=["obj-a"],
        prerequisites=[],
        misconceptions=[],
        examples=[],
        diagnostic_items=[],
        practice_templates=[],
        mastery_policy_id=policy.id,
        source_ids=[],
        content_version=course.content_version,
    )
    db_session.add(node)
    db_session.flush()

    templates = []
    # Three MC questions with known-correct options A, B, A.
    for correct, stem in [
        ("A", "Pick A. B is wrong."),
        ("B", "Pick B. A is wrong."),
        ("A", "Pick A again."),
    ]:
        template = KnowledgeQuestionTemplate(
            id=uuid4(),
            node_id=node.id,
            kind="MULTIPLE_CHOICE",
            prompt_template=stem,
            parameter_schema={},
            answer_schema={"type": "string", "const": correct},
            test_case_ids=[],
            source_ids=[],
            content_version=course.content_version,
        )
        db_session.add(template)
        templates.append(template)
    db_session.flush()
    return node, templates


def _answer(template: KnowledgeQuestionTemplate) -> str:
    return template.answer_schema["const"]


def test_get_questions_returns_node_templates(
    client: TestClient, db_session: Session, student_auth
) -> None:
    _, token = student_auth
    node, templates = _seed_node_with_questions(db_session)

    response = client.get(f"/api/v1/practice/nodes/{node.id}/questions", headers=_headers(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["node_id"] == str(node.id)
    returned_ids = {q["id"] for q in body["questions"]}
    assert returned_ids == {str(t.id) for t in templates}
    assert len(body["questions"]) == len(templates)
    first = body["questions"][0]
    assert first["kind"] == "MULTIPLE_CHOICE"
    assert first["prompt_template"]
    # The correct answer (const) MUST NOT be exposed on the GET endpoint.
    assert "answer_schema" not in first
    assert "const" not in first
    assert "answer" not in first


def test_attempt_all_correct_scores_full_and_records_evidence(
    client: TestClient, db_session: Session, student_auth
) -> None:
    student, token = student_auth
    node, templates = _seed_node_with_questions(db_session)

    payload = {
        "node_id": str(node.id),
        "answers": [{"question_id": str(t.id), "selected_answer": _answer(t)} for t in templates],
    }
    response = client.post(
        "/api/v1/practice/attempt",
        json=payload,
        headers=_headers(token, "attempt-all-correct", "trc_practice_all"),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["score"] == pytest.approx(1.0)
    assert body["evidence_id"]
    assert len(body["per_question"]) == len(templates)
    assert all(item["correct"] for item in body["per_question"])
    per_q_map = {item["question_id"]: item for item in body["per_question"]}
    assert per_q_map[str(templates[0].id)]["correct"] is True

    # Evidence was recorded with the self-test event type and score payload.
    evidence_count = db_session.scalar(
        select(func.count())
        .select_from(EvidenceEvent)
        .where(EvidenceEvent.student_id == student.id)
    )
    assert evidence_count == 1
    evidence = db_session.scalar(
        select(EvidenceEvent).where(EvidenceEvent.student_id == student.id)
    )
    assert evidence is not None
    assert evidence.event_type == "SELF_TEST_ATTEMPTED"
    assert evidence.node_id == node.id
    assert evidence.course_id == COURSE_ID
    assert evidence.payload["score"] == pytest.approx(1.0)
    assert len(evidence.payload["per_question"]) == len(templates)


def test_attempt_mixed_answers_scores_fractionally(
    client: TestClient, db_session: Session, student_auth
) -> None:
    _, token = student_auth
    node, templates = _seed_node_with_questions(db_session)

    # Correct, wrong, correct → 2/3.
    answers = [
        {"question_id": str(templates[0].id), "selected_answer": _answer(templates[0])},
        {"question_id": str(templates[1].id), "selected_answer": "A"},  # wrong (correct is B)
        {"question_id": str(templates[2].id), "selected_answer": _answer(templates[2])},
    ]
    payload = {"node_id": str(node.id), "answers": answers}
    response = client.post(
        "/api/v1/practice/attempt",
        json=payload,
        headers=_headers(token, "attempt-mixed", "trc_practice_mixed"),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["score"] == pytest.approx(2 / 3)
    correct_flags = {item["question_id"]: item["correct"] for item in body["per_question"]}
    assert correct_flags[str(templates[0].id)] is True
    assert correct_flags[str(templates[1].id)] is False
    assert correct_flags[str(templates[2].id)] is True


def test_attempt_exposes_explanation_field_shape(
    client: TestClient, db_session: Session, student_auth
) -> None:
    _, token = student_auth
    node, templates = _seed_node_with_questions(db_session)

    payload = {
        "node_id": str(node.id),
        "answers": [
            {"question_id": str(templates[0].id), "selected_answer": "WRONG"},
        ],
    }
    response = client.post(
        "/api/v1/practice/attempt",
        json=payload,
        headers=_headers(token, "attempt-shape", "trc_practice_shape"),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    item = body["per_question"][0]
    # Per-question feedback must carry the deterministic correctness flag.
    assert item["correct"] is False
    # ``explanation`` is part of the contract shape; it may be null when the
    # template has none, but the key must be present.
    assert "explanation" in item


def test_attempt_is_idempotent_on_key_replay(
    client: TestClient, db_session: Session, student_auth
) -> None:
    student, token = student_auth
    node, templates = _seed_node_with_questions(db_session)

    payload = {
        "node_id": str(node.id),
        "answers": [{"question_id": str(t.id), "selected_answer": _answer(t)} for t in templates],
    }
    headers = _headers(token, "attempt-idempotent", "trc_practice_idem")
    first = client.post("/api/v1/practice/attempt", json=payload, headers=headers)
    second = client.post("/api/v1/practice/attempt", json=payload, headers=headers)

    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json()["evidence_id"] == second.json()["evidence_id"]
    assert first.json()["score"] == second.json()["score"]
    # No duplicate evidence row on replay.
    evidence_count = db_session.scalar(
        select(func.count())
        .select_from(EvidenceEvent)
        .where(EvidenceEvent.student_id == student.id)
    )
    assert evidence_count == 1


def test_attempt_requires_idempotency_key(
    client: TestClient, db_session: Session, student_auth
) -> None:
    _, token = student_auth
    node, templates = _seed_node_with_questions(db_session)
    payload = {
        "node_id": str(node.id),
        "answers": [{"question_id": str(t.id), "selected_answer": _answer(t)} for t in templates],
    }
    response = client.post("/api/v1/practice/attempt", json=payload, headers=_headers(token))
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_unauthenticated_requests_are_rejected(client: TestClient, db_session: Session) -> None:
    node, _ = _seed_node_with_questions(db_session)
    get_response = client.get(f"/api/v1/practice/nodes/{node.id}/questions")
    assert get_response.status_code == 401

    post_response = client.post(
        "/api/v1/practice/attempt",
        json={"node_id": str(node.id), "answers": []},
        headers={"Idempotency-Key": "no-auth"},
    )
    assert post_response.status_code == 401


def test_unknown_node_returns_404(client: TestClient, db_session: Session, student_auth) -> None:
    _, token = student_auth
    missing_id = uuid4()
    response = client.get(f"/api/v1/practice/nodes/{missing_id}/questions", headers=_headers(token))
    assert response.status_code == 404


def test_attempt_with_unknown_question_is_404(
    client: TestClient, db_session: Session, student_auth
) -> None:
    _, token = student_auth
    node, _ = _seed_node_with_questions(db_session)
    payload = {
        "node_id": str(node.id),
        "answers": [{"question_id": str(uuid4()), "selected_answer": "A"}],
    }
    response = client.post(
        "/api/v1/practice/attempt",
        json=payload,
        headers=_headers(token, "attempt-unknown-q"),
    )
    assert response.status_code == 404


def test_attempt_does_not_advance_mastery_contract(
    client: TestClient, db_session: Session, student_auth
) -> None:
    """CONTRACT: a self-test attempt records evidence but must NOT mutate the
    deterministic mastery state for the node."""

    student, token = student_auth
    node, templates = _seed_node_with_questions(db_session)

    # Pre-seed a mastery state in a known status so we can detect mutation.
    pre_state = MasteryState(
        tenant_id=student.tenant_id,
        student_id=student.id,
        course_id=COURSE_ID,
        node_id=node.id,
        status=MasteryStatus.LEARNING,
        version=1,
        last_evidence_event_id=None,
    )
    db_session.add(pre_state)
    db_session.flush()

    payload = {
        "node_id": str(node.id),
        "answers": [{"question_id": str(t.id), "selected_answer": _answer(t)} for t in templates],
    }
    response = client.post(
        "/api/v1/practice/attempt",
        json=payload,
        headers=_headers(token, "attempt-no-mastery", "trc_practice_no_mastery"),
    )
    assert response.status_code == 200, response.text

    db_session.expire_all()
    post_state = db_session.get(MasteryState, pre_state.id)
    assert post_state is not None
    # Status and version MUST be unchanged: the deterministic engine owns mastery.
    assert post_state.status == MasteryStatus.LEARNING
    assert post_state.version == 1
    # The attempt evidence is not linked as the mastery-driving evidence.
    assert post_state.last_evidence_event_id is None

    # Sanity: there is exactly one piece of evidence and it is a self-test.
    evidence = db_session.scalar(
        select(EvidenceEvent).where(EvidenceEvent.student_id == student.id)
    )
    assert evidence is not None
    assert evidence.event_type == "SELF_TEST_ATTEMPTED"


def test_attempt_records_trace_id(client: TestClient, db_session: Session, student_auth) -> None:
    student, token = student_auth
    node, templates = _seed_node_with_questions(db_session)
    payload = {
        "node_id": str(node.id),
        "answers": [{"question_id": str(t.id), "selected_answer": _answer(t)} for t in templates],
    }
    response = client.post(
        "/api/v1/practice/attempt",
        json=payload,
        headers=_headers(token, "attempt-trace", "trc_practice_trace"),
    )
    assert response.status_code == 200, response.text
    evidence = db_session.scalar(
        select(EvidenceEvent).where(EvidenceEvent.student_id == student.id)
    )
    assert evidence is not None
    assert evidence.trace_id == "trc_practice_trace"
    # created_at is timezone-aware ( EvidenceEvent stores tz-aware timestamps ).
    assert evidence.created_at.tzinfo is not None
    assert evidence.created_at <= datetime.now(UTC)
