"""Deterministic assessment and mastery transition tests (BE-004)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.mastery import (
    AssessmentFacts,
    IllegalMasteryTransition,
    InvalidAssessmentFacts,
    MasteryPolicy,
    record_assessment_and_decide,
    transition_mastery,
)
from app.models import (
    AssessmentResult,
    MasteryState,
    MasteryStateHistory,
    MasteryStatus,
    ReviewStatus,
    UserStatus,
)
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant

COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
NODE_ID = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")
NOW = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
POLICY = MasteryPolicy(
    independence_min=0.7,
    transfer_min=0.6,
    max_hints_for_mastery=1,
    review_delay_days=7,
)


@pytest.fixture()
def student(db_session: Session):
    tenant = get_or_create_tenant(db_session, slug=f"mastery-{uuid4().hex}", name="Mastery Test")
    db_session.flush()
    user = create_student_user(
        db_session,
        tenant_id=tenant.id,
        email=f"mastery-{uuid4().hex}@test.local",
        password_hash=hash_password("ValidPass1!"),
    )
    user.status = UserStatus.ACTIVE
    db_session.flush()
    return user


def _facts(**overrides: object) -> AssessmentFacts:
    values: dict[str, object] = {
        "correct": True,
        "hidden_tests_passed": True,
        "hints_used": 0,
        "support_level": 0,
        "independence_score": 0.9,
        "transfer_score": 0.8,
        "platform_error": False,
    }
    values.update(overrides)
    return AssessmentFacts(**values)  # type: ignore[arg-type]


def _decide(
    db_session: Session,
    student,
    facts: AssessmentFacts,
    *,
    event_id: str,
    now: datetime = NOW,
):
    return record_assessment_and_decide(
        db_session,
        facts,
        policy=POLICY,
        tenant_id=student.tenant_id,
        student_id=student.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        evidence_event_id=event_id,
        now=now,
    )


def test_helped_pass_does_not_become_initial_mastery(db_session: Session, student) -> None:
    decision = _decide(
        db_session,
        student,
        _facts(hints_used=2, support_level=2, independence_score=0.45),
        event_id="evt_assessment_helped",
    )
    assert decision.state is not None
    assert decision.state.status == MasteryStatus.PASSED_WITH_HELP
    assert decision.review is None


def test_initial_mastery_creates_review_atomically(db_session: Session, student) -> None:
    decision = _decide(db_session, student, _facts(), event_id="evt_assessment_initial")
    assert decision.state is not None
    assert decision.state.status == MasteryStatus.INITIAL_MASTERY
    assert decision.state.initial_mastery_at == NOW
    assert decision.review is not None
    assert decision.review.status == ReviewStatus.SCHEDULED
    assert decision.review.due_at == NOW + timedelta(days=7)


def test_failed_first_attempt_stays_learning(db_session: Session, student) -> None:
    decision = _decide(
        db_session,
        student,
        _facts(correct=False, hidden_tests_passed=False, independence_score=0.2),
        event_id="evt_assessment_failed",
    )
    assert decision.state is not None
    assert decision.state.status == MasteryStatus.LEARNING
    assert decision.review is None


def test_platform_error_records_assessment_without_formal_transition(
    db_session: Session, student
) -> None:
    decision = _decide(
        db_session,
        student,
        _facts(correct=False, hidden_tests_passed=False, platform_error=True),
        event_id="evt_platform_failure",
    )
    assert decision.state is None
    assert decision.review is None
    assert decision.assessment.platform_error is True
    assert db_session.scalar(select(func.count()).select_from(MasteryState)) == 0


def test_platform_error_preserves_existing_mastery_and_review(db_session: Session, student) -> None:
    initial = _decide(db_session, student, _facts(), event_id="evt_before_platform")
    platform = _decide(
        db_session,
        student,
        _facts(correct=False, hidden_tests_passed=False, platform_error=True),
        event_id="evt_platform_after_mastery",
        now=NOW + timedelta(minutes=1),
    )
    assert initial.state is not None and initial.review is not None
    assert platform.state is not None and platform.review is not None
    assert platform.state.id == initial.state.id
    assert platform.state.status == MasteryStatus.INITIAL_MASTERY
    assert platform.review.id == initial.review.id


def test_same_evidence_is_replay_safe(db_session: Session, student) -> None:
    first = _decide(db_session, student, _facts(), event_id="evt_replay")
    second = _decide(db_session, student, _facts(), event_id="evt_replay")
    assert second.assessment.id == first.assessment.id
    assert second.state is not None and first.state is not None
    assert second.state.id == first.state.id
    assert db_session.scalar(select(func.count()).select_from(AssessmentResult)) == 1
    assert db_session.scalar(select(func.count()).select_from(MasteryStateHistory)) == 2


def test_illegal_transition_is_rejected(db_session: Session, student) -> None:
    decision = _decide(
        db_session,
        student,
        _facts(correct=False, hidden_tests_passed=False),
        event_id="evt_learning",
    )
    assert decision.state is not None
    with pytest.raises(IllegalMasteryTransition):
        transition_mastery(
            db_session,
            decision.state,
            MasteryStatus.STABLE_MASTERY,
            reason="cannot skip delayed review",
            evidence_event_id="evt_illegal",
            now=NOW,
        )


@pytest.mark.parametrize(
    "facts",
    [
        _facts(hints_used=-1),
        _facts(support_level=4),
        _facts(independence_score=1.1),
        _facts(transfer_score=-0.1),
    ],
)
def test_invalid_assessment_facts_are_rejected_before_write(
    db_session: Session, student, facts: AssessmentFacts
) -> None:
    with pytest.raises(InvalidAssessmentFacts):
        _decide(
            db_session,
            student,
            facts,
            event_id=f"evt_invalid_{uuid4().hex}",
        )
