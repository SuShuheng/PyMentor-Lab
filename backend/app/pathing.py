"""Pure path-policy validation plus versioned path persistence (BE-004)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    LearningPath,
    LearningPathStatus,
    LearningPathStep,
    PathStepKind,
    PathValidationStatus,
    User,
)


class InvalidPathProposal(ValueError):
    """The proposal or validated result cannot become formal state."""


class PathVersionConflict(Exception):
    """The expected current path version is stale."""


class PathScopeError(Exception):
    """The student is outside the requested tenant scope."""


@dataclass(frozen=True)
class StepProposal:
    node_id: UUID
    estimated_minutes: int
    kind: PathStepKind = PathStepKind.LEARN
    scenario_key: str = "default"
    platform_error: bool = False
    source_metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class PathProposal:
    steps: list[StepProposal]


@dataclass(frozen=True)
class DueReview:
    review_id: UUID
    node_id: UUID
    estimated_minutes: int = 15
    scenario_key: str = "delayed-review"


@dataclass(frozen=True)
class ValidationContext:
    daily_minutes: int
    prerequisites: dict[UUID, tuple[UUID, ...]]
    completed_nodes: set[UUID]
    due_reviews: list[DueReview]
    mastery_policy_nodes: set[UUID]
    resource_ready_nodes: set[UUID]
    active_node_ids: set[UUID]
    template_fallback_nodes: set[UUID]
    forbidden_node_ids: set[UUID]


@dataclass(frozen=True)
class ValidationFinding:
    code: str
    node_id: UUID | None
    repaired: bool


@dataclass(frozen=True)
class ValidatedStep:
    node_id: UUID
    kind: PathStepKind
    estimated_minutes: int
    scenario_key: str
    validation_status: PathValidationStatus
    source_metadata: dict[str, Any]


@dataclass(frozen=True)
class ValidatedPath:
    steps: tuple[ValidatedStep, ...]
    findings: tuple[ValidationFinding, ...]


def _finding(code: str, node_id: UUID | None, *, repaired: bool) -> ValidationFinding:
    return ValidationFinding(code=code, node_id=node_id, repaired=repaired)


def _validated_parts(
    proposal: StepProposal,
    *,
    daily_minutes: int,
    scenario_key: str,
    status: PathValidationStatus,
    metadata: dict[str, Any],
    findings: list[ValidationFinding],
) -> list[ValidatedStep]:
    if proposal.estimated_minutes < 1:
        findings.append(_finding("INVALID_ESTIMATE", proposal.node_id, repaired=False))
        return []
    if daily_minutes < 1:
        findings.append(_finding("TIME_BUDGET_UNAVAILABLE", proposal.node_id, repaired=False))
        return []
    if proposal.estimated_minutes <= daily_minutes:
        return [
            ValidatedStep(
                node_id=proposal.node_id,
                kind=proposal.kind,
                estimated_minutes=proposal.estimated_minutes,
                scenario_key=scenario_key,
                validation_status=status,
                source_metadata=metadata,
            )
        ]

    findings.append(_finding("TIME_SPLIT", proposal.node_id, repaired=True))
    parts: list[ValidatedStep] = []
    remaining = proposal.estimated_minutes
    part_number = 1
    while remaining > 0:
        minutes = min(daily_minutes, remaining)
        parts.append(
            ValidatedStep(
                node_id=proposal.node_id,
                kind=proposal.kind,
                estimated_minutes=minutes,
                scenario_key=f"{scenario_key}-part-{part_number}",
                validation_status=PathValidationStatus.REPAIRED,
                source_metadata={**metadata, "part": part_number},
            )
        )
        remaining -= minutes
        part_number += 1
    return parts


def validate_path(proposal: PathProposal, context: ValidationContext) -> ValidatedPath:
    """Apply the frozen path rules in deterministic order.

    Due reviews are emitted first. New-learning proposals then receive
    prerequisite insertion, time splitting, policy/resource/state checks,
    and active-work variant repair. Platform errors are recorded but never
    translated into remediation.
    """

    if context.daily_minutes < 0:
        raise InvalidPathProposal("daily_minutes must be non-negative")

    findings: list[ValidationFinding] = []
    steps: list[ValidatedStep] = []
    identities: set[tuple[UUID, PathStepKind, str]] = set()
    planned_nodes: set[UUID] = set(context.completed_nodes)

    for review in sorted(
        context.due_reviews, key=lambda item: (str(item.node_id), str(item.review_id))
    ):
        minutes = min(review.estimated_minutes, context.daily_minutes)
        if minutes < 1:
            findings.append(_finding("TIME_BUDGET_UNAVAILABLE", review.node_id, repaired=False))
            continue
        review_step = ValidatedStep(
            node_id=review.node_id,
            kind=PathStepKind.REVIEW,
            estimated_minutes=minutes,
            scenario_key=review.scenario_key,
            validation_status=PathValidationStatus.VALIDATED,
            source_metadata={"review_id": str(review.review_id)},
        )
        identity = (review_step.node_id, review_step.kind, review_step.scenario_key)
        if identity not in identities:
            identities.add(identity)
            steps.append(review_step)

    visiting: set[UUID] = set()

    def append_proposal(item: StepProposal, *, prerequisite: bool = False) -> None:
        if item.platform_error:
            findings.append(_finding("PLATFORM_ERROR_IGNORED", item.node_id, repaired=False))
            return
        if item.node_id in visiting:
            findings.append(_finding("PREREQUISITE_CYCLE", item.node_id, repaired=False))
            return

        visiting.add(item.node_id)
        prerequisite_unavailable = False
        for required in context.prerequisites.get(item.node_id, ()):
            if required in planned_nodes:
                continue
            prerequisite_item = StepProposal(
                node_id=required,
                estimated_minutes=min(15, max(context.daily_minutes, 1)),
                kind=PathStepKind.LEARN,
                scenario_key=f"prerequisite-{required}",
                source_metadata={"inserted_for": str(item.node_id)},
            )
            before = len(steps)
            append_proposal(prerequisite_item, prerequisite=True)
            if len(steps) > before:
                findings.append(_finding("PREREQUISITE_INSERTED", required, repaired=True))
            elif required not in planned_nodes:
                prerequisite_unavailable = True
                findings.append(_finding("PREREQUISITE_UNAVAILABLE", item.node_id, repaired=False))
        visiting.remove(item.node_id)
        if prerequisite_unavailable:
            return

        if item.node_id not in context.mastery_policy_nodes:
            findings.append(_finding("MASTERY_POLICY_MISSING", item.node_id, repaired=False))
            return
        if item.node_id in context.forbidden_node_ids:
            findings.append(_finding("NODE_STATE_FORBIDDEN", item.node_id, repaired=False))
            return

        scenario_key = item.scenario_key.strip()
        if not scenario_key or len(scenario_key) > 128:
            findings.append(_finding("INVALID_SCENARIO_KEY", item.node_id, repaired=False))
            return
        status = PathValidationStatus.REPAIRED if prerequisite else PathValidationStatus.VALIDATED
        metadata = dict(item.source_metadata or {})
        if item.node_id not in context.resource_ready_nodes:
            if item.node_id not in context.template_fallback_nodes:
                findings.append(_finding("RESOURCE_UNAVAILABLE", item.node_id, repaired=False))
                return
            scenario_key = f"template-{scenario_key}"
            status = PathValidationStatus.FALLBACK
            findings.append(_finding("RESOURCE_TEMPLATE_FALLBACK", item.node_id, repaired=True))
        if item.node_id in context.active_node_ids:
            scenario_key = f"{scenario_key}-variant"
            status = PathValidationStatus.REPAIRED
            findings.append(_finding("ACTIVE_DUPLICATE_VARIANT", item.node_id, repaired=True))

        parts = _validated_parts(
            item,
            daily_minutes=context.daily_minutes,
            scenario_key=scenario_key,
            status=status,
            metadata=metadata,
            findings=findings,
        )
        for part in parts:
            identity = (part.node_id, part.kind, part.scenario_key)
            if identity in identities:
                findings.append(_finding("DUPLICATE_STEP_REMOVED", part.node_id, repaired=True))
                continue
            identities.add(identity)
            steps.append(part)
            planned_nodes.add(part.node_id)

    for item in proposal.steps:
        append_proposal(item)

    return ValidatedPath(steps=tuple(steps), findings=tuple(findings))


def _finding_payload(finding: ValidationFinding) -> dict[str, Any]:
    payload = asdict(finding)
    payload["node_id"] = str(finding.node_id) if finding.node_id is not None else None
    return payload


def _constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def persist_validated_path(
    db: Session,
    *,
    tenant_id: UUID,
    student_id: UUID,
    course_id: UUID,
    expected_version: int,
    validated: ValidatedPath,
) -> LearningPath:
    """Persist a non-empty validated path and supersede its predecessor."""

    if expected_version < 0:
        raise InvalidPathProposal("expected_version must be non-negative")
    if not validated.steps:
        raise InvalidPathProposal("a validated path must contain at least one step")
    in_scope = db.scalar(select(User.id).where(User.id == student_id, User.tenant_id == tenant_id))
    if in_scope is None:
        raise PathScopeError("student is not available in tenant scope")

    current = db.scalar(
        select(LearningPath)
        .where(
            LearningPath.tenant_id == tenant_id,
            LearningPath.student_id == student_id,
            LearningPath.course_id == course_id,
            LearningPath.status == LearningPathStatus.CURRENT,
        )
        .with_for_update()
    )
    actual_version = current.version if current is not None else 0
    if actual_version != expected_version:
        raise PathVersionConflict(f"expected {expected_version}, actual {actual_version}")

    path = LearningPath(
        tenant_id=tenant_id,
        student_id=student_id,
        course_id=course_id,
        version=actual_version + 1,
        status=LearningPathStatus.CURRENT,
        source_proposal={},
        validation_findings=[_finding_payload(item) for item in validated.findings],
    )
    try:
        with db.begin_nested():
            if current is not None:
                current.status = LearningPathStatus.SUPERSEDED
                db.flush()
            db.add(path)
            db.flush()
            for position, step in enumerate(validated.steps, start=1):
                db.add(
                    LearningPathStep(
                        tenant_id=tenant_id,
                        path_id=path.id,
                        position=position,
                        node_id=step.node_id,
                        kind=step.kind,
                        estimated_minutes=step.estimated_minutes,
                        scenario_key=step.scenario_key,
                        source_metadata=step.source_metadata,
                        validation_status=step.validation_status,
                        validation_outcome={},
                    )
                )
            db.flush()
    except IntegrityError as exc:
        if _constraint_name(exc) in {
            "uq_learning_path_current",
            "uq_learning_path_version",
        }:
            latest = db.scalar(
                select(LearningPath.version)
                .where(
                    LearningPath.tenant_id == tenant_id,
                    LearningPath.student_id == student_id,
                    LearningPath.course_id == course_id,
                )
                .order_by(LearningPath.version.desc())
                .limit(1)
            )
            raise PathVersionConflict(
                f"expected {expected_version}, actual {latest or actual_version}"
            ) from exc
        raise
    return path
