"""Persisted delayed-review clock and stable-mastery tests (BE-004)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evidence import record_evidence
from app.mastery import AssessmentFacts, MasteryPolicy, record_assessment_and_decide
from app.models import (
    MasteryStatus,
    ReviewAttempt,
    ReviewAttemptOutcome,
    ReviewSchedule,
    ReviewStatus,
    UserStatus,
)
from app.reviews import (
    InvalidReviewOperation,
    ReviewFacts,
    complete_review,
    mark_due_reviews,
    reschedule_review,
)
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant

COURSE_ID = UUID("00000000-0000-0000-0000-000000000311")
NODE_ID = UUID("00000000-0000-0000-0000-000000000312")
INITIAL_AT = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
POLICY = MasteryPolicy(
    independence_min=0.7,
    transfer_min=0.6,
    max_hints_for_mastery=1,
    review_delay_days=7,
)


@pytest.fixture()
def initial_mastery(db_session: Session):
    tenant = get_or_create_tenant(db_session, slug=f"review-{uuid4().hex}", name="Review Test")
    db_session.flush()
    student = create_student_user(
        db_session,
        tenant_id=tenant.id,
        email=f"review-{uuid4().hex}@test.local",
        password_hash=hash_password("ValidPass1!"),
    )
    student.status = UserStatus.ACTIVE
    db_session.flush()
    decision = record_assessment_and_decide(
        db_session,
        AssessmentFacts(
            correct=True,
            hidden_tests_passed=True,
            hints_used=0,
            support_level=0,
            independence_score=0.9,
            transfer_score=0.8,
            platform_error=False,
        ),
        policy=POLICY,
        tenant_id=tenant.id,
        student_id=student.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        evidence_event_id=f"evt_initial_{uuid4().hex}",
        now=INITIAL_AT,
    )
    assert decision.state is not None and decision.review is not None
    return student, decision.state, decision.review


def _accepted_evidence(
    db_session: Session, student, *, event_id: str, created_at: datetime
) -> None:
    event = record_evidence(
        db_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        event_id=event_id,
        event_type="REVIEW_COMPLETED",
        trace_id=f"trace_{event_id}",
        course_id=COURSE_ID,
        node_id=NODE_ID,
    )
    assert event is not None
    event.created_at = created_at
    db_session.flush()


def _review_facts(schedule: ReviewSchedule, **overrides: object) -> ReviewFacts:
    values: dict[str, object] = {
        "correct": True,
        "hidden_tests_passed": True,
        "hints_used": 0,
        "support_level": 0,
        "independence_score": 0.9,
        "transfer_score": 0.8,
        "platform_error": False,
        "scenario_key": schedule.scenario_key,
    }
    values.update(overrides)
    return ReviewFacts(**values)  # type: ignore[arg-type]


def test_due_review_uses_persisted_utc_timestamp(db_session: Session, initial_mastery) -> None:
    _, state, schedule = initial_mastery
    before = mark_due_reviews(db_session, now=schedule.due_at - timedelta(seconds=1))
    due = mark_due_reviews(db_session, now=schedule.due_at)
    assert before == []
    assert [item.id for item in due] == [schedule.id]
    assert schedule.status == ReviewStatus.DUE
    assert state.status == MasteryStatus.REVIEW_REQUIRED


def test_postpone_never_reduces_mastery(db_session: Session, initial_mastery) -> None:
    _, state, schedule = initial_mastery
    new_due = schedule.due_at + timedelta(days=2)
    reschedule_review(
        db_session,
        review_id=schedule.id,
        requested_due_at=new_due,
        now=schedule.due_at - timedelta(days=1),
        expected_version=schedule.version,
    )
    assert state.status == MasteryStatus.INITIAL_MASTERY
    assert schedule.due_at == new_due
    assert schedule.reschedule_count == 1


def test_stable_mastery_requires_new_unassisted_review_evidence(
    db_session: Session, initial_mastery
) -> None:
    student, state, schedule = initial_mastery
    mark_due_reviews(db_session, now=schedule.due_at)
    event_id = f"evt_review_pass_{uuid4().hex}"
    _accepted_evidence(
        db_session,
        student,
        event_id=event_id,
        created_at=schedule.due_at + timedelta(minutes=1),
    )
    result = complete_review(
        db_session,
        review_id=schedule.id,
        facts=_review_facts(schedule),
        evidence_event_id=event_id,
        now=schedule.due_at + timedelta(minutes=1),
    )
    assert result.status == MasteryStatus.STABLE_MASTERY
    assert schedule.status == ReviewStatus.COMPLETED
    attempt = db_session.scalar(
        select(ReviewAttempt).where(ReviewAttempt.review_schedule_id == schedule.id)
    )
    assert attempt is not None and attempt.outcome == ReviewAttemptOutcome.PASSED
    assert state.stable_mastery_at == schedule.due_at + timedelta(minutes=1)


def test_old_evidence_cannot_create_stable_mastery(db_session: Session, initial_mastery) -> None:
    student, state, schedule = initial_mastery
    mark_due_reviews(db_session, now=schedule.due_at)
    event_id = f"evt_review_old_{uuid4().hex}"
    _accepted_evidence(
        db_session,
        student,
        event_id=event_id,
        created_at=INITIAL_AT - timedelta(seconds=1),
    )
    complete_review(
        db_session,
        review_id=schedule.id,
        facts=_review_facts(schedule),
        evidence_event_id=event_id,
        now=schedule.due_at + timedelta(minutes=1),
    )
    assert state.status == MasteryStatus.REVIEW_REQUIRED
    retry = db_session.scalar(
        select(ReviewSchedule).where(ReviewSchedule.status == ReviewStatus.SCHEDULED)
    )
    assert retry is not None and retry.id != schedule.id


def test_evidence_created_before_review_due_is_not_delayed_review(
    db_session: Session, initial_mastery
) -> None:
    student, state, schedule = initial_mastery
    mark_due_reviews(db_session, now=schedule.due_at)
    event_id = f"evt_review_too_early_{uuid4().hex}"
    _accepted_evidence(
        db_session,
        student,
        event_id=event_id,
        created_at=schedule.due_at - timedelta(seconds=1),
    )
    complete_review(
        db_session,
        review_id=schedule.id,
        facts=_review_facts(schedule),
        evidence_event_id=event_id,
        now=schedule.due_at + timedelta(minutes=1),
    )
    assert state.status == MasteryStatus.REVIEW_REQUIRED


def test_assisted_review_fails_stability_and_schedules_variant(
    db_session: Session, initial_mastery
) -> None:
    student, state, schedule = initial_mastery
    mark_due_reviews(db_session, now=schedule.due_at)
    event_id = f"evt_review_helped_{uuid4().hex}"
    _accepted_evidence(
        db_session,
        student,
        event_id=event_id,
        created_at=schedule.due_at + timedelta(minutes=1),
    )
    complete_review(
        db_session,
        review_id=schedule.id,
        facts=_review_facts(schedule, hints_used=2, support_level=1),
        evidence_event_id=event_id,
        now=schedule.due_at + timedelta(minutes=1),
    )
    assert state.status == MasteryStatus.REVIEW_REQUIRED
    retry = db_session.scalar(
        select(ReviewSchedule).where(ReviewSchedule.status == ReviewStatus.SCHEDULED)
    )
    assert retry is not None
    assert retry.scenario_key != schedule.scenario_key


def test_even_policy_allowed_hint_is_not_unassisted_stable_mastery(
    db_session: Session, initial_mastery
) -> None:
    student, state, schedule = initial_mastery
    assert schedule.hint_ceiling == 1
    mark_due_reviews(db_session, now=schedule.due_at)
    event_id = f"evt_review_one_hint_{uuid4().hex}"
    _accepted_evidence(
        db_session,
        student,
        event_id=event_id,
        created_at=schedule.due_at + timedelta(minutes=1),
    )
    complete_review(
        db_session,
        review_id=schedule.id,
        facts=_review_facts(schedule, hints_used=1),
        evidence_event_id=event_id,
        now=schedule.due_at + timedelta(minutes=1),
    )
    assert state.status == MasteryStatus.REVIEW_REQUIRED


def test_platform_error_does_not_change_mastery_or_schedule_retry(
    db_session: Session, initial_mastery
) -> None:
    student, state, schedule = initial_mastery
    mark_due_reviews(db_session, now=schedule.due_at)
    event_id = f"evt_review_platform_{uuid4().hex}"
    _accepted_evidence(
        db_session,
        student,
        event_id=event_id,
        created_at=schedule.due_at + timedelta(minutes=1),
    )
    complete_review(
        db_session,
        review_id=schedule.id,
        facts=_review_facts(schedule, platform_error=True),
        evidence_event_id=event_id,
        now=schedule.due_at + timedelta(minutes=1),
    )
    assert state.status == MasteryStatus.REVIEW_REQUIRED
    assert schedule.status == ReviewStatus.DUE
    attempt = db_session.scalar(
        select(ReviewAttempt).where(ReviewAttempt.review_schedule_id == schedule.id)
    )
    assert attempt is not None
    assert attempt.outcome == ReviewAttemptOutcome.PLATFORM_ERROR


def test_review_clock_requires_timezone_aware_values(db_session: Session, initial_mastery) -> None:
    _, _, schedule = initial_mastery
    with pytest.raises(InvalidReviewOperation):
        mark_due_reviews(db_session, now=datetime(2026, 7, 24, 8, 0))
    with pytest.raises(InvalidReviewOperation):
        reschedule_review(
            db_session,
            review_id=schedule.id,
            requested_due_at=datetime(2026, 7, 25, 8, 0),
            now=INITIAL_AT,
        )
