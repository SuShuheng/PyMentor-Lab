"""Evidence-driven, versioned profile projection tests (BE-004)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProfileDimension, ProfileDimensionScore, UserStatus
from app.profile_projection import (
    DimensionUpdate,
    InvalidProfileUpdate,
    ProfileScopeError,
    ProfileVersionConflict,
    create_profile_dispute,
    project_profile,
)
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant


@pytest.fixture()
def student(db_session: Session):
    tenant = get_or_create_tenant(db_session, slug=f"profile-{uuid4().hex}", name="Profile Test")
    db_session.flush()
    user = create_student_user(
        db_session,
        tenant_id=tenant.id,
        email=f"profile-{uuid4().hex}@test.local",
        password_hash=hash_password("ValidPass1!"),
    )
    user.status = UserStatus.ACTIVE
    db_session.flush()
    return user


def _update(
    dimension: str = "DEBUGGING",
    *,
    scope_key: str = "loops",
    score: float = 0.45,
    confidence: float = 0.8,
    support_level: int = 2,
) -> DimensionUpdate:
    return DimensionUpdate(
        dimension=dimension,
        scope_key=scope_key,
        score=score,
        confidence=confidence,
        support_level=support_level,
    )


def test_profile_projection_versions_monotonically_and_copies_snapshot(
    db_session: Session, student
) -> None:
    first = project_profile(
        db_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        source_event_id="evt_profile_1",
        expected_version=0,
        updates=[
            _update(),
            _update(
                "TESTING",
                scope_key="loops",
                score=0.35,
                confidence=0.7,
                support_level=2,
            ),
        ],
    )
    second = project_profile(
        db_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        source_event_id="evt_profile_2",
        expected_version=1,
        updates=[_update(score=0.65, confidence=0.9, support_level=1)],
    )

    assert (first.version, second.version) == (1, 2)
    second_scores = list(
        db_session.scalars(
            select(ProfileDimensionScore).where(
                ProfileDimensionScore.profile_version_id == second.id
            )
        )
    )
    by_dimension = {item.dimension: item for item in second_scores}
    assert by_dimension[ProfileDimension.DEBUGGING].score == 0.65
    assert by_dimension[ProfileDimension.TESTING].score == 0.35


def test_profile_projection_rejects_stale_version(db_session: Session, student) -> None:
    project_profile(
        db_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        source_event_id="evt_profile_current",
        expected_version=0,
        updates=[_update()],
    )

    with pytest.raises(ProfileVersionConflict, match="expected 0, actual 1"):
        project_profile(
            db_session,
            tenant_id=student.tenant_id,
            student_id=student.id,
            source_event_id="evt_profile_stale",
            expected_version=0,
            updates=[_update(score=0.7)],
        )


@pytest.mark.parametrize(
    "update",
    [
        _update(dimension="UNKNOWN"),
        _update(score=1.1),
        _update(confidence=-0.1),
        _update(support_level=4),
        _update(scope_key=""),
    ],
)
def test_profile_projection_validates_updates_before_writing(
    db_session: Session, student, update: DimensionUpdate
) -> None:
    with pytest.raises(InvalidProfileUpdate):
        project_profile(
            db_session,
            tenant_id=student.tenant_id,
            student_id=student.id,
            source_event_id=f"evt_invalid_{uuid4().hex}",
            expected_version=0,
            updates=[update],
        )


def test_profile_projection_rejects_cross_tenant_scope(db_session: Session, student) -> None:
    with pytest.raises(ProfileScopeError):
        project_profile(
            db_session,
            tenant_id=uuid4(),
            student_id=student.id,
            source_event_id="evt_wrong_tenant",
            expected_version=0,
            updates=[_update()],
        )


def test_profile_dispute_is_scoped_and_append_only(db_session: Session, student) -> None:
    profile = project_profile(
        db_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        source_event_id="evt_disputed",
        expected_version=0,
        updates=[_update()],
    )
    dispute = create_profile_dispute(
        db_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        profile_version_id=profile.id,
        reason="The score omits my latest debugging attempt.",
    )
    assert dispute.profile_version_id == profile.id
    assert dispute.reason.startswith("The score")

    with pytest.raises(ProfileScopeError):
        create_profile_dispute(
            db_session,
            tenant_id=uuid4(),
            student_id=student.id,
            profile_version_id=profile.id,
            reason="Cross-tenant lookup must fail.",
        )
