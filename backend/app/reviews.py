"""Persisted delayed-review clock and completion policy (BE-004)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.mastery import transition_mastery
from app.models import (
    EvidenceEvent,
    MasteryState,
    MasteryStatus,
    ReviewAttempt,
    ReviewAttemptOutcome,
    ReviewSchedule,
    ReviewStatus,
)

MAX_RESCHEDULE_COUNT = 3
MAX_POSTPONE_DAYS = 14
RETRY_DELAY_DAYS = 3
REVIEW_INDEPENDENCE_MIN = 0.7
REVIEW_TRANSFER_MIN = 0.6


class InvalidReviewOperation(ValueError):
    """Review timing, scope, facts, or state violates formal policy."""


class ReviewVersionConflict(InvalidReviewOperation):
    """The supplied optimistic review version is stale."""


@dataclass(frozen=True)
class ReviewFacts:
    correct: bool
    hidden_tests_passed: bool
    hints_used: int
    support_level: int
    independence_score: float
    transfer_score: float
    platform_error: bool
    scenario_key: str


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidReviewOperation(f"{name} must be timezone-aware")


def _validate_facts(facts: ReviewFacts) -> None:
    if facts.hints_used < 0:
        raise InvalidReviewOperation("hints_used must be non-negative")
    if not 0 <= facts.support_level <= 3:
        raise InvalidReviewOperation("support_level must be between 0 and 3")
    if not 0.0 <= facts.independence_score <= 1.0:
        raise InvalidReviewOperation("independence_score must be between 0 and 1")
    if not 0.0 <= facts.transfer_score <= 1.0:
        raise InvalidReviewOperation("transfer_score must be between 0 and 1")
    if not facts.scenario_key.strip() or len(facts.scenario_key) > 128:
        raise InvalidReviewOperation("scenario_key must contain 1..128 characters")


def mark_due_reviews(db: Session, *, now: datetime) -> list[ReviewSchedule]:
    """Move persisted schedules due at or before ``now`` into formal due state."""

    _require_aware(now, "now")
    reviews = list(
        db.scalars(
            select(ReviewSchedule)
            .where(
                ReviewSchedule.status == ReviewStatus.SCHEDULED,
                ReviewSchedule.due_at <= now,
            )
            .order_by(ReviewSchedule.due_at, ReviewSchedule.id)
            .with_for_update(skip_locked=True)
        )
    )
    for review in reviews:
        review.status = ReviewStatus.DUE
        review.version += 1
        state = db.get(MasteryState, review.mastery_state_id)
        if state is None:
            raise InvalidReviewOperation("review references a missing mastery state")
        if state.status == MasteryStatus.INITIAL_MASTERY:
            transition_mastery(
                db,
                state,
                MasteryStatus.REVIEW_REQUIRED,
                reason="DELAYED_REVIEW_DUE",
                evidence_event_id=None,
                now=now,
            )
    db.flush()
    return reviews


def reschedule_review(
    db: Session,
    *,
    review_id: UUID,
    requested_due_at: datetime,
    now: datetime,
    expected_version: int | None = None,
) -> ReviewSchedule:
    """Postpone one active review without changing mastery or profile scores."""

    _require_aware(now, "now")
    _require_aware(requested_due_at, "requested_due_at")
    review = db.scalar(
        select(ReviewSchedule).where(ReviewSchedule.id == review_id).with_for_update()
    )
    if review is None or review.status not in {ReviewStatus.SCHEDULED, ReviewStatus.DUE}:
        raise InvalidReviewOperation("active review not found")
    if expected_version is not None and review.version != expected_version:
        raise ReviewVersionConflict(f"expected {expected_version}, actual {review.version}")
    if requested_due_at <= now:
        raise InvalidReviewOperation("requested due time must be in the future")
    if review.reschedule_count >= MAX_RESCHEDULE_COUNT:
        raise InvalidReviewOperation("review reschedule limit reached")
    if requested_due_at > review.original_due_at + timedelta(days=MAX_POSTPONE_DAYS):
        raise InvalidReviewOperation("requested due time exceeds postponement limit")
    review.due_at = requested_due_at
    review.status = ReviewStatus.SCHEDULED
    review.reschedule_count += 1
    review.last_rescheduled_at = now
    review.version += 1
    db.flush()
    return review


def _accepted_review_evidence(
    db: Session, schedule: ReviewSchedule, evidence_event_id: str
) -> EvidenceEvent:
    evidence = db.scalar(
        select(EvidenceEvent).where(
            EvidenceEvent.event_id == evidence_event_id,
            EvidenceEvent.tenant_id == schedule.tenant_id,
            EvidenceEvent.student_id == schedule.student_id,
            EvidenceEvent.course_id == schedule.course_id,
            EvidenceEvent.node_id == schedule.node_id,
            EvidenceEvent.event_type == "REVIEW_COMPLETED",
        )
    )
    if evidence is None:
        raise InvalidReviewOperation("accepted review evidence not found in scope")
    return evidence


def _append_attempt(
    db: Session,
    schedule: ReviewSchedule,
    facts: ReviewFacts,
    *,
    evidence_event_id: str,
    outcome: ReviewAttemptOutcome,
    now: datetime,
) -> ReviewAttempt:
    attempt = ReviewAttempt(
        tenant_id=schedule.tenant_id,
        review_schedule_id=schedule.id,
        assessment_result_id=None,
        evidence_event_id=evidence_event_id,
        outcome=outcome,
        scenario_key=facts.scenario_key,
        hints_used=facts.hints_used,
        support_level=facts.support_level,
        completed_at=now,
    )
    db.add(attempt)
    db.flush()
    return attempt


def _schedule_retry(
    db: Session, schedule: ReviewSchedule, state: MasteryState, *, now: datetime
) -> ReviewSchedule:
    due_at = now + timedelta(days=RETRY_DELAY_DAYS)
    retry = ReviewSchedule(
        tenant_id=schedule.tenant_id,
        student_id=schedule.student_id,
        course_id=schedule.course_id,
        node_id=schedule.node_id,
        mastery_state_id=state.id,
        scenario_key=f"{schedule.scenario_key}-retry-{schedule.reschedule_count + 1}",
        due_at=due_at,
        original_due_at=due_at,
        hint_ceiling=schedule.hint_ceiling,
        status=ReviewStatus.SCHEDULED,
    )
    db.add(retry)
    db.flush()
    return retry


def complete_review(
    db: Session,
    *,
    review_id: UUID,
    facts: ReviewFacts,
    evidence_event_id: str,
    now: datetime,
) -> MasteryState:
    """Record one immutable review attempt and decide stable mastery or retry."""

    _require_aware(now, "now")
    _validate_facts(facts)
    clean_event_id = evidence_event_id.strip()
    if not clean_event_id or len(clean_event_id) > 128:
        raise InvalidReviewOperation("evidence_event_id must contain 1..128 characters")
    schedule = db.scalar(
        select(ReviewSchedule).where(ReviewSchedule.id == review_id).with_for_update()
    )
    if schedule is None or schedule.status not in {
        ReviewStatus.SCHEDULED,
        ReviewStatus.DUE,
    }:
        raise InvalidReviewOperation("active review not found")
    state = db.scalar(
        select(MasteryState).where(MasteryState.id == schedule.mastery_state_id).with_for_update()
    )
    if state is None:
        raise InvalidReviewOperation("review references a missing mastery state")

    replay = db.scalar(
        select(ReviewAttempt).where(ReviewAttempt.evidence_event_id == clean_event_id)
    )
    if replay is not None:
        if replay.review_schedule_id != schedule.id:
            raise InvalidReviewOperation("review evidence was already used out of scope")
        return state
    evidence = _accepted_review_evidence(db, schedule, clean_event_id)

    if facts.platform_error:
        _append_attempt(
            db,
            schedule,
            facts,
            evidence_event_id=clean_event_id,
            outcome=ReviewAttemptOutcome.PLATFORM_ERROR,
            now=now,
        )
        return state

    initial_at = state.initial_mastery_at
    delayed_evidence = (
        initial_at is not None
        and evidence.created_at > initial_at
        and evidence.created_at >= schedule.due_at
    )
    passed = (
        schedule.status == ReviewStatus.DUE
        and now >= schedule.due_at
        and facts.scenario_key == schedule.scenario_key
        and facts.correct
        and facts.hidden_tests_passed
        and facts.hints_used == 0
        and facts.support_level == 0
        and facts.independence_score >= REVIEW_INDEPENDENCE_MIN
        and facts.transfer_score >= REVIEW_TRANSFER_MIN
        and delayed_evidence
    )
    _append_attempt(
        db,
        schedule,
        facts,
        evidence_event_id=clean_event_id,
        outcome=ReviewAttemptOutcome.PASSED if passed else ReviewAttemptOutcome.FAILED,
        now=now,
    )
    schedule.status = ReviewStatus.COMPLETED
    schedule.version += 1
    db.flush()

    if passed:
        if state.status not in {
            MasteryStatus.REVIEW_REQUIRED,
            MasteryStatus.INITIAL_MASTERY,
        }:
            raise InvalidReviewOperation("mastery state cannot accept a passed review")
        transition_mastery(
            db,
            state,
            MasteryStatus.STABLE_MASTERY,
            reason="DELAYED_REVIEW_PASSED",
            evidence_event_id=clean_event_id,
            now=now,
        )
        return state

    if state.status in {MasteryStatus.INITIAL_MASTERY, MasteryStatus.STABLE_MASTERY}:
        transition_mastery(
            db,
            state,
            MasteryStatus.REVIEW_REQUIRED,
            reason="DELAYED_REVIEW_RETRY_REQUIRED",
            evidence_event_id=clean_event_id,
            now=now,
        )
    elif state.status != MasteryStatus.REVIEW_REQUIRED:
        raise InvalidReviewOperation("mastery state cannot accept a failed review")
    _schedule_retry(db, schedule, state, now=now)
    return state
