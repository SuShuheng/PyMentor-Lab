"""Deterministic assessment recording and mastery decisions (BE-004)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AssessmentResult,
    MasteryState,
    MasteryStateHistory,
    MasteryStatus,
    ReviewSchedule,
    ReviewStatus,
    User,
)


class InvalidAssessmentFacts(ValueError):
    """Assessment facts or policy values are outside deterministic bounds."""


class IllegalMasteryTransition(Exception):
    """A caller attempted a transition outside the frozen state machine."""


class MasteryScopeError(Exception):
    """The student or replayed assessment is outside tenant scope."""


@dataclass(frozen=True)
class AssessmentFacts:
    correct: bool
    hidden_tests_passed: bool
    hints_used: int
    support_level: int
    independence_score: float
    transfer_score: float
    platform_error: bool


@dataclass(frozen=True)
class MasteryPolicy:
    independence_min: float
    transfer_min: float
    max_hints_for_mastery: int
    review_delay_days: int


@dataclass(frozen=True)
class MasteryDecision:
    assessment: AssessmentResult
    state: MasteryState | None
    review: ReviewSchedule | None


ALLOWED_TRANSITIONS: dict[MasteryStatus, set[MasteryStatus]] = {
    MasteryStatus.UNSEEN: {MasteryStatus.LEARNING},
    MasteryStatus.LEARNING: {
        MasteryStatus.PASSED_WITH_HELP,
        MasteryStatus.INITIAL_MASTERY,
    },
    MasteryStatus.PASSED_WITH_HELP: {
        MasteryStatus.INITIAL_MASTERY,
        MasteryStatus.REVIEW_REQUIRED,
    },
    MasteryStatus.INITIAL_MASTERY: {
        MasteryStatus.REVIEW_REQUIRED,
        MasteryStatus.STABLE_MASTERY,
    },
    MasteryStatus.REVIEW_REQUIRED: {
        MasteryStatus.INITIAL_MASTERY,
        MasteryStatus.STABLE_MASTERY,
    },
    MasteryStatus.STABLE_MASTERY: {MasteryStatus.REVIEW_REQUIRED},
}


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidAssessmentFacts(f"{name} must be timezone-aware")


def _validate(facts: AssessmentFacts, policy: MasteryPolicy) -> None:
    if facts.hints_used < 0:
        raise InvalidAssessmentFacts("hints_used must be non-negative")
    if not 0 <= facts.support_level <= 3:
        raise InvalidAssessmentFacts("support_level must be between 0 and 3")
    if not 0.0 <= facts.independence_score <= 1.0:
        raise InvalidAssessmentFacts("independence_score must be between 0 and 1")
    if not 0.0 <= facts.transfer_score <= 1.0:
        raise InvalidAssessmentFacts("transfer_score must be between 0 and 1")
    if not 0.0 <= policy.independence_min <= 1.0:
        raise InvalidAssessmentFacts("independence_min must be between 0 and 1")
    if not 0.0 <= policy.transfer_min <= 1.0:
        raise InvalidAssessmentFacts("transfer_min must be between 0 and 1")
    if policy.max_hints_for_mastery < 0:
        raise InvalidAssessmentFacts("max_hints_for_mastery must be non-negative")
    if policy.review_delay_days < 1:
        raise InvalidAssessmentFacts("review_delay_days must be positive")


def transition_mastery(
    db: Session,
    state: MasteryState,
    target: MasteryStatus,
    *,
    reason: str,
    evidence_event_id: str | None,
    now: datetime,
) -> MasteryState:
    """Apply one legal transition and append immutable history."""

    _require_aware(now, "now")
    current = state.status
    if target == current:
        return state
    if target not in ALLOWED_TRANSITIONS[current]:
        raise IllegalMasteryTransition(f"{current.value} -> {target.value} is not allowed")
    state.status = target
    state.version += 1
    state.last_evidence_event_id = evidence_event_id
    if target == MasteryStatus.INITIAL_MASTERY:
        state.initial_mastery_at = now
    elif target == MasteryStatus.STABLE_MASTERY:
        state.stable_mastery_at = now
    db.add(
        MasteryStateHistory(
            tenant_id=state.tenant_id,
            mastery_state_id=state.id,
            from_status=current,
            to_status=target,
            reason=reason,
            evidence_event_id=evidence_event_id,
            created_at=now,
        )
    )
    db.flush()
    return state


def _create_learning_state(
    db: Session,
    *,
    tenant_id: UUID,
    student_id: UUID,
    course_id: UUID,
    node_id: UUID,
    evidence_event_id: str,
    now: datetime,
) -> MasteryState:
    state = MasteryState(
        tenant_id=tenant_id,
        student_id=student_id,
        course_id=course_id,
        node_id=node_id,
        status=MasteryStatus.LEARNING,
        version=1,
        last_evidence_event_id=evidence_event_id,
    )
    db.add(state)
    db.flush()
    db.add(
        MasteryStateHistory(
            tenant_id=tenant_id,
            mastery_state_id=state.id,
            from_status=MasteryStatus.UNSEEN,
            to_status=MasteryStatus.LEARNING,
            reason="FIRST_ACCEPTED_ATTEMPT",
            evidence_event_id=evidence_event_id,
            created_at=now,
        )
    )
    db.flush()
    return state


def _active_review(db: Session, state: MasteryState) -> ReviewSchedule | None:
    return db.scalar(
        select(ReviewSchedule).where(
            ReviewSchedule.mastery_state_id == state.id,
            ReviewSchedule.status.in_([ReviewStatus.SCHEDULED, ReviewStatus.DUE]),
        )
    )


def _schedule_initial_review(
    db: Session,
    state: MasteryState,
    *,
    policy: MasteryPolicy,
    now: datetime,
) -> ReviewSchedule:
    due_at = now + timedelta(days=policy.review_delay_days)
    existing = _active_review(db, state)
    if existing is not None:
        existing.status = ReviewStatus.SCHEDULED
        existing.due_at = due_at
        existing.original_due_at = due_at
        existing.hint_ceiling = policy.max_hints_for_mastery
        existing.version += 1
        db.flush()
        return existing
    review = ReviewSchedule(
        tenant_id=state.tenant_id,
        student_id=state.student_id,
        course_id=state.course_id,
        node_id=state.node_id,
        mastery_state_id=state.id,
        scenario_key=f"{state.node_id}-review-{state.version}",
        due_at=due_at,
        original_due_at=due_at,
        hint_ceiling=policy.max_hints_for_mastery,
        status=ReviewStatus.SCHEDULED,
    )
    db.add(review)
    db.flush()
    return review


def _current_state(
    db: Session,
    *,
    tenant_id: UUID,
    student_id: UUID,
    course_id: UUID,
    node_id: UUID,
) -> MasteryState | None:
    return db.scalar(
        select(MasteryState)
        .where(
            MasteryState.tenant_id == tenant_id,
            MasteryState.student_id == student_id,
            MasteryState.course_id == course_id,
            MasteryState.node_id == node_id,
        )
        .with_for_update()
    )


def record_assessment_and_decide(
    db: Session,
    facts: AssessmentFacts,
    *,
    policy: MasteryPolicy,
    tenant_id: UUID,
    student_id: UUID,
    course_id: UUID,
    node_id: UUID,
    evidence_event_id: str,
    now: datetime,
) -> MasteryDecision:
    """Record immutable facts and advance formal mastery deterministically."""

    _require_aware(now, "now")
    _validate(facts, policy)
    clean_event_id = evidence_event_id.strip()
    if not clean_event_id or len(clean_event_id) > 128:
        raise InvalidAssessmentFacts("evidence_event_id must contain 1..128 characters")
    student_exists = db.scalar(
        select(User.id).where(User.id == student_id, User.tenant_id == tenant_id)
    )
    if student_exists is None:
        raise MasteryScopeError("student is not available in tenant scope")

    replay = db.scalar(
        select(AssessmentResult).where(AssessmentResult.evidence_event_id == clean_event_id)
    )
    if replay is not None:
        if replay.tenant_id != tenant_id or replay.student_id != student_id:
            raise MasteryScopeError("assessment replay is outside student scope")
        state = _current_state(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            course_id=course_id,
            node_id=node_id,
        )
        return MasteryDecision(
            assessment=replay,
            state=state,
            review=_active_review(db, state) if state is not None else None,
        )

    assessment = AssessmentResult(
        tenant_id=tenant_id,
        student_id=student_id,
        course_id=course_id,
        node_id=node_id,
        evidence_event_id=clean_event_id,
        correct=facts.correct,
        hidden_tests_passed=facts.hidden_tests_passed,
        hints_used=facts.hints_used,
        support_level=facts.support_level,
        independence_score=facts.independence_score,
        transfer_score=facts.transfer_score,
        platform_error=facts.platform_error,
        facts=asdict(facts),
        created_at=now,
    )
    db.add(assessment)
    db.flush()
    if facts.platform_error:
        preserved_state = _current_state(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            course_id=course_id,
            node_id=node_id,
        )
        return MasteryDecision(
            assessment=assessment,
            state=preserved_state,
            review=(_active_review(db, preserved_state) if preserved_state is not None else None),
        )

    state = _current_state(
        db,
        tenant_id=tenant_id,
        student_id=student_id,
        course_id=course_id,
        node_id=node_id,
    )
    if state is None:
        state = _create_learning_state(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            course_id=course_id,
            node_id=node_id,
            evidence_event_id=clean_event_id,
            now=now,
        )

    passed = facts.correct and facts.hidden_tests_passed
    qualifies_for_initial = (
        passed
        and facts.hints_used <= policy.max_hints_for_mastery
        and facts.support_level == 0
        and facts.independence_score >= policy.independence_min
        and facts.transfer_score >= policy.transfer_min
    )
    review: ReviewSchedule | None = None
    if qualifies_for_initial and state.status in {
        MasteryStatus.LEARNING,
        MasteryStatus.PASSED_WITH_HELP,
        MasteryStatus.REVIEW_REQUIRED,
    }:
        transition_mastery(
            db,
            state,
            MasteryStatus.INITIAL_MASTERY,
            reason="ASSESSMENT_THRESHOLDS_MET",
            evidence_event_id=clean_event_id,
            now=now,
        )
        review = _schedule_initial_review(db, state, policy=policy, now=now)
    elif passed and state.status == MasteryStatus.LEARNING:
        transition_mastery(
            db,
            state,
            MasteryStatus.PASSED_WITH_HELP,
            reason="ASSESSMENT_PASSED_WITH_SUPPORT",
            evidence_event_id=clean_event_id,
            now=now,
        )
    elif state.status == MasteryStatus.INITIAL_MASTERY:
        review = _active_review(db, state)

    return MasteryDecision(assessment=assessment, state=state, review=review)
