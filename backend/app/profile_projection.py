"""Deterministic, evidence-driven profile projection (BE-004).

Each accepted projection creates a complete immutable snapshot. Callers must
provide the current expected version; stale or concurrent writers receive an
explicit conflict instead of silently overwriting formal state.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ProfileDimension,
    ProfileDimensionScore,
    ProfileDispute,
    ProfileVersion,
    User,
)


class ProfileVersionConflict(Exception):
    """The supplied optimistic profile version is stale."""


class ProfileScopeError(Exception):
    """The student or profile is outside the requested tenant scope."""


class InvalidProfileUpdate(ValueError):
    """A proposed dimension update violates the frozen profile policy."""


@dataclass(frozen=True)
class DimensionUpdate:
    dimension: str
    scope_key: str
    score: float
    confidence: float
    support_level: int


@dataclass(frozen=True)
class _NormalizedUpdate:
    dimension: ProfileDimension
    scope_key: str
    score: float
    confidence: float
    support_level: int


def _normalize_updates(updates: list[DimensionUpdate]) -> list[_NormalizedUpdate]:
    if not updates:
        raise InvalidProfileUpdate("at least one dimension update is required")

    normalized: list[_NormalizedUpdate] = []
    seen: set[tuple[ProfileDimension, str]] = set()
    for update in updates:
        try:
            dimension = ProfileDimension(update.dimension)
        except ValueError as exc:
            raise InvalidProfileUpdate(f"unknown profile dimension: {update.dimension}") from exc
        scope_key = update.scope_key.strip()
        if not scope_key or len(scope_key) > 128:
            raise InvalidProfileUpdate("scope_key must contain 1..128 characters")
        if not 0.0 <= update.score <= 1.0:
            raise InvalidProfileUpdate("score must be between 0 and 1")
        if not 0.0 <= update.confidence <= 1.0:
            raise InvalidProfileUpdate("confidence must be between 0 and 1")
        if not 0 <= update.support_level <= 3:
            raise InvalidProfileUpdate("support_level must be between 0 and 3")
        key = (dimension, scope_key)
        if key in seen:
            raise InvalidProfileUpdate("duplicate dimension/scope update")
        seen.add(key)
        normalized.append(
            _NormalizedUpdate(
                dimension=dimension,
                scope_key=scope_key,
                score=update.score,
                confidence=update.confidence,
                support_level=update.support_level,
            )
        )
    return normalized


def _require_student_scope(db: Session, *, tenant_id: UUID, student_id: UUID) -> None:
    exists = db.scalar(select(User.id).where(User.id == student_id, User.tenant_id == tenant_id))
    if exists is None:
        raise ProfileScopeError("student is not available in tenant scope")


def _constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def project_profile(
    db: Session,
    *,
    tenant_id: UUID,
    student_id: UUID,
    source_event_id: str,
    expected_version: int,
    updates: list[DimensionUpdate],
) -> ProfileVersion:
    """Create the next complete immutable profile snapshot.

    The source event has already passed evidence acceptance. This service owns
    only deterministic projection and optimistic concurrency; the surrounding
    UoW owns audit, Outbox, and commit.
    """

    normalized = _normalize_updates(updates)
    if expected_version < 0:
        raise InvalidProfileUpdate("expected_version must be non-negative")
    clean_event_id = source_event_id.strip()
    if not clean_event_id or len(clean_event_id) > 128:
        raise InvalidProfileUpdate("source_event_id must contain 1..128 characters")
    _require_student_scope(db, tenant_id=tenant_id, student_id=student_id)

    current = db.scalar(
        select(ProfileVersion)
        .where(
            ProfileVersion.tenant_id == tenant_id,
            ProfileVersion.student_id == student_id,
        )
        .order_by(ProfileVersion.version.desc())
        .limit(1)
        .with_for_update()
    )
    actual_version = current.version if current is not None else 0
    if actual_version != expected_version:
        raise ProfileVersionConflict(f"expected {expected_version}, actual {actual_version}")

    snapshot: dict[tuple[ProfileDimension, str], tuple[float, float, int]] = {}
    if current is not None:
        previous_scores = db.scalars(
            select(ProfileDimensionScore).where(
                ProfileDimensionScore.profile_version_id == current.id
            )
        )
        snapshot.update(
            {
                (row.dimension, row.scope_key): (
                    row.score,
                    row.confidence,
                    row.support_level,
                )
                for row in previous_scores
            }
        )
    for update in normalized:
        snapshot[(update.dimension, update.scope_key)] = (
            update.score,
            update.confidence,
            update.support_level,
        )

    profile = ProfileVersion(
        tenant_id=tenant_id,
        student_id=student_id,
        version=actual_version + 1,
        source_event_id=clean_event_id,
    )
    try:
        with db.begin_nested():
            db.add(profile)
            db.flush()
            for (dimension, scope_key), (score, confidence, support_level) in sorted(
                snapshot.items(), key=lambda item: (item[0][0].value, item[0][1])
            ):
                db.add(
                    ProfileDimensionScore(
                        tenant_id=tenant_id,
                        profile_version_id=profile.id,
                        dimension=dimension,
                        scope_key=scope_key,
                        score=score,
                        confidence=confidence,
                        support_level=support_level,
                    )
                )
            db.flush()
    except IntegrityError as exc:
        if _constraint_name(exc) in {
            "uq_profile_student_version",
            "uq_profile_student_source_event",
        }:
            latest = db.scalar(
                select(ProfileVersion.version)
                .where(
                    ProfileVersion.tenant_id == tenant_id,
                    ProfileVersion.student_id == student_id,
                )
                .order_by(ProfileVersion.version.desc())
                .limit(1)
            )
            raise ProfileVersionConflict(
                f"expected {expected_version}, actual {latest or actual_version}"
            ) from exc
        raise
    return profile


def create_profile_dispute(
    db: Session,
    *,
    tenant_id: UUID,
    student_id: UUID,
    profile_version_id: UUID,
    reason: str,
) -> ProfileDispute:
    """Append a dispute after verifying the referenced profile is student-scoped."""

    clean_reason = reason.strip()
    if not clean_reason or len(clean_reason) > 2000:
        raise InvalidProfileUpdate("reason must contain 1..2000 characters")
    profile = db.scalar(
        select(ProfileVersion).where(
            ProfileVersion.id == profile_version_id,
            ProfileVersion.tenant_id == tenant_id,
            ProfileVersion.student_id == student_id,
        )
    )
    if profile is None:
        raise ProfileScopeError("profile is not available in student scope")
    dispute = ProfileDispute(
        tenant_id=tenant_id,
        student_id=student_id,
        profile_version_id=profile.id,
        reason=clean_reason,
    )
    db.add(dispute)
    db.flush()
    return dispute
