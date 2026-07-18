"""Deterministic path validation and persistence tests (BE-004)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.models import LearningPathStatus, PathStepKind, UserStatus
from app.pathing import (
    DueReview,
    InvalidPathProposal,
    PathProposal,
    PathVersionConflict,
    StepProposal,
    ValidationContext,
    persist_validated_path,
    validate_path,
)
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant

COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
TARGET = UUID("e5809fab-7e1e-5b7f-b384-ead7958d0b59")
PREREQ = UUID("45f059fa-a2da-52c2-a01f-865f0628226f")
OLD_NODE = UUID("1272e982-8681-5ea2-a88a-db5b73b69e70")
REVIEW_ID = UUID("00000000-0000-0000-0000-000000000105")


@pytest.fixture()
def student(db_session: Session):
    tenant = get_or_create_tenant(db_session, slug=f"path-{uuid4().hex}", name="Path Test")
    db_session.flush()
    user = create_student_user(
        db_session,
        tenant_id=tenant.id,
        email=f"path-{uuid4().hex}@test.local",
        password_hash=hash_password("ValidPass1!"),
    )
    user.status = UserStatus.ACTIVE
    db_session.flush()
    return user


def _context(**overrides: object) -> ValidationContext:
    values: dict[str, object] = {
        "daily_minutes": 30,
        "prerequisites": {},
        "completed_nodes": set(),
        "due_reviews": [],
        "mastery_policy_nodes": {TARGET, PREREQ, OLD_NODE},
        "resource_ready_nodes": {TARGET, PREREQ, OLD_NODE},
        "active_node_ids": set(),
        "template_fallback_nodes": set(),
        "forbidden_node_ids": set(),
    }
    values.update(overrides)
    return ValidationContext(**values)  # type: ignore[arg-type]


def test_due_review_precedes_new_learning() -> None:
    result = validate_path(
        PathProposal(steps=[StepProposal(node_id=TARGET, estimated_minutes=20)]),
        _context(due_reviews=[DueReview(review_id=REVIEW_ID, node_id=OLD_NODE)]),
    )
    assert result.steps[0].kind == PathStepKind.REVIEW
    assert result.steps[0].node_id == OLD_NODE
    assert result.steps[1].node_id == TARGET


def test_validator_inserts_prerequisite_and_splits_time() -> None:
    result = validate_path(
        PathProposal(
            steps=[
                StepProposal(
                    node_id=TARGET,
                    estimated_minutes=75,
                    kind=PathStepKind.LEARN,
                    scenario_key="loops-long",
                )
            ]
        ),
        _context(prerequisites={TARGET: (PREREQ,)}),
    )
    assert [step.node_id for step in result.steps[:2]] == [PREREQ, TARGET]
    assert all(step.estimated_minutes <= 30 for step in result.steps)
    assert {finding.code for finding in result.findings} >= {
        "PREREQUISITE_INSERTED",
        "TIME_SPLIT",
    }


def test_missing_mastery_policy_rejects_step() -> None:
    result = validate_path(
        PathProposal(steps=[StepProposal(node_id=TARGET, estimated_minutes=20)]),
        _context(mastery_policy_nodes={PREREQ, OLD_NODE}),
    )
    assert result.steps == ()
    assert result.findings[0].code == "MASTERY_POLICY_MISSING"
    assert result.findings[0].repaired is False


def test_unrepairable_prerequisite_blocks_target() -> None:
    result = validate_path(
        PathProposal(steps=[StepProposal(node_id=TARGET, estimated_minutes=20)]),
        _context(
            prerequisites={TARGET: (PREREQ,)},
            mastery_policy_nodes={TARGET, OLD_NODE},
        ),
    )
    assert result.steps == ()
    assert {finding.code for finding in result.findings} >= {
        "MASTERY_POLICY_MISSING",
        "PREREQUISITE_UNAVAILABLE",
    }


def test_missing_resource_uses_declared_template_fallback() -> None:
    result = validate_path(
        PathProposal(steps=[StepProposal(node_id=TARGET, estimated_minutes=20)]),
        _context(
            resource_ready_nodes={PREREQ, OLD_NODE},
            template_fallback_nodes={TARGET},
        ),
    )
    assert result.steps[0].scenario_key.startswith("template-")
    assert result.steps[0].validation_status == "FALLBACK"
    assert result.findings[0].code == "RESOURCE_TEMPLATE_FALLBACK"


def test_missing_resource_without_fallback_rejects_step() -> None:
    result = validate_path(
        PathProposal(steps=[StepProposal(node_id=TARGET, estimated_minutes=20)]),
        _context(resource_ready_nodes={PREREQ, OLD_NODE}),
    )
    assert result.steps == ()
    assert result.findings[0].code == "RESOURCE_UNAVAILABLE"


def test_duplicate_active_work_becomes_scenario_variant() -> None:
    result = validate_path(
        PathProposal(
            steps=[
                StepProposal(
                    node_id=TARGET,
                    estimated_minutes=20,
                    scenario_key="loops-v1",
                )
            ]
        ),
        _context(active_node_ids={TARGET}),
    )
    assert result.steps[0].scenario_key == "loops-v1-variant"
    assert result.findings[0].code == "ACTIVE_DUPLICATE_VARIANT"


def test_forbidden_node_state_rejects_step() -> None:
    result = validate_path(
        PathProposal(steps=[StepProposal(node_id=TARGET, estimated_minutes=20)]),
        _context(forbidden_node_ids={TARGET}),
    )
    assert result.steps == ()
    assert result.findings[0].code == "NODE_STATE_FORBIDDEN"


def test_platform_error_never_creates_remediation() -> None:
    result = validate_path(
        PathProposal(
            steps=[
                StepProposal(
                    node_id=TARGET,
                    estimated_minutes=20,
                    platform_error=True,
                )
            ]
        ),
        _context(prerequisites={TARGET: (PREREQ,)}),
    )
    assert result.steps == ()
    assert [finding.code for finding in result.findings] == ["PLATFORM_ERROR_IGNORED"]


def test_persisted_path_versions_and_supersedes_atomically(db_session: Session, student) -> None:
    first_validated = validate_path(
        PathProposal(steps=[StepProposal(node_id=TARGET, estimated_minutes=20)]),
        _context(),
    )
    first = persist_validated_path(
        db_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        course_id=COURSE_ID,
        expected_version=0,
        validated=first_validated,
    )
    second_validated = validate_path(
        PathProposal(steps=[StepProposal(node_id=PREREQ, estimated_minutes=10)]),
        _context(),
    )
    second = persist_validated_path(
        db_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        course_id=COURSE_ID,
        expected_version=1,
        validated=second_validated,
    )
    assert (first.version, first.status) == (1, LearningPathStatus.SUPERSEDED)
    assert (second.version, second.status) == (2, LearningPathStatus.CURRENT)

    with pytest.raises(PathVersionConflict, match="expected 1, actual 2"):
        persist_validated_path(
            db_session,
            tenant_id=student.tenant_id,
            student_id=student.id,
            course_id=COURSE_ID,
            expected_version=1,
            validated=second_validated,
        )


def test_empty_validated_path_cannot_be_persisted(db_session: Session, student) -> None:
    rejected = validate_path(
        PathProposal(steps=[StepProposal(node_id=TARGET, estimated_minutes=20)]),
        _context(mastery_policy_nodes=set()),
    )
    with pytest.raises(InvalidPathProposal):
        persist_validated_path(
            db_session,
            tenant_id=student.tenant_id,
            student_id=student.id,
            course_id=COURSE_ID,
            expected_version=0,
            validated=rejected,
        )
