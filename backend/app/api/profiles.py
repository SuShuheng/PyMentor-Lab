"""Student profile query and dispute commands (BE-004)."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.command_idempotency import begin_command, scope_for_request
from app.contracts.learning import (
    OnboardingSubmissionRequest,
    OnboardingSubmissionView,
    ProfileDimensionView,
    ProfileDisputeRequest,
    ProfileDisputeView,
    ProfileSnapshot,
)
from app.db import get_db
from app.evidence import record_audit, record_evidence
from app.idempotency import save_response
from app.models import (
    CourseCatalog,
    CourseChapter,
    KnowledgeNode,
    LearningPath,
    LearningPathStatus,
    ProfileDimensionScore,
    ProfileVersion,
    User,
)
from app.models.base import RoleName
from app.pathing import (
    PathProposal,
    StepProposal,
    ValidatedPath,
    ValidationContext,
    persist_validated_path,
    validate_path,
)
from app.profile_projection import create_profile_dispute, project_onboarding
from app.rbac import get_current_user
from app.services import get_user_roles
from app.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/profiles", tags=["learning-profiles"])


@router.get("/current", response_model=ProfileSnapshot)
async def get_current_profile(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ProfileSnapshot:
    profile = db.scalar(
        select(ProfileVersion)
        .where(
            ProfileVersion.tenant_id == user.tenant_id,
            ProfileVersion.student_id == user.id,
        )
        .order_by(ProfileVersion.version.desc())
        .limit(1)
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="profile not found")
    scores = list(
        db.scalars(
            select(ProfileDimensionScore)
            .where(ProfileDimensionScore.profile_version_id == profile.id)
            .order_by(ProfileDimensionScore.dimension, ProfileDimensionScore.scope_key)
        )
    )
    return ProfileSnapshot(
        id=str(profile.id),
        student_id=str(profile.student_id),
        version=profile.version,
        source_event_id=profile.source_event_id,
        dimensions=[
            ProfileDimensionView(
                dimension=item.dimension.value,
                scope_key=item.scope_key,
                score=item.score,
                confidence=item.confidence,
                support_level=item.support_level,
            )
            for item in scores
        ],
    )


@router.post(
    "/disputes",
    status_code=status.HTTP_201_CREATED,
    response_model=ProfileDisputeView,
)
async def dispute_profile(
    body: ProfileDisputeRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProfileDisputeView | JSONResponse:
    try:
        profile_version_id = UUID(body.profile_version_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="profile_version_id must be a UUID",
        ) from exc
    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    cached = begin_command(db, scope)
    if cached is not None:
        return JSONResponse(
            content=cached.response_body or {},
            status_code=cached.response_status or status.HTTP_201_CREATED,
        )

    trace_id = str(request.state.trace_id)
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        dispute = create_profile_dispute(
            db,
            tenant_id=user.tenant_id,
            student_id=user.id,
            profile_version_id=profile_version_id,
            reason=body.reason,
        )
        view = ProfileDisputeView(
            id=str(dispute.id),
            profile_version_id=str(dispute.profile_version_id),
            reason=dispute.reason,
        )
        response_body = view.model_dump(mode="json")
        record_audit(
            db,
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            action="PROFILE_DISPUTED",
            resource_type="profile_dispute",
            resource_id=str(dispute.id),
            trace_id=trace_id,
        )
        uow.publish(
            event_type="PROFILE_DISPUTED",
            aggregate_type="profile_dispute",
            aggregate_id=str(dispute.id),
            tenant_id=user.tenant_id,
            trace_id=trace_id,
            payload={"profile_version_id": str(dispute.profile_version_id)},
        )
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_201_CREATED,
            response_body=response_body,
        )
        uow.commit()
    return view


def _require_student_role(db: Session, user: User) -> None:
    """Onboarding is a student-only command; non-students get 403."""

    if RoleName.STUDENT.value not in set(get_user_roles(db, user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="student role required",
        )


def _resolve_published_course_id(db: Session) -> UUID | None:
    """Return the first published course id, or None if none exists.

    Mirrors ``app.api.knowledge._resolve_course_id`` but returns None instead
    of raising 404 — onboarding should not hard-fail on an empty catalogue,
    it should just skip path compilation (``path_compiled=False``) so the rest
    of the projection/evidence flow still completes.
    """

    return db.scalar(
        select(CourseCatalog.id)
        .where(CourseCatalog.published.is_(True))
        .order_by(CourseCatalog.created_at, CourseCatalog.id)
        .limit(1)
    )


# Map the self-reported weekly time-band to a daily-minutes budget used to
# validate the student's first learning path. Values are deliberately modest
# (single-step initial path) so the first day is always achievable; the
# planner-driven replan worker (PATH_REPLAN_REQUESTED) can expand later. The
# band labels mirror the V1.0 frontend onboarding options.
_WEEKLY_BAND_DAILY_MINUTES: dict[str, int] = {
    "4 hours+": 30,  # ~4-5h/week → ~30 focused minutes/day
    "2-4 hours": 25,  # ~2-4h/week → ~25 focused minutes/day
    "<2 hours": 15,  # <2h/week → ~15 focused minutes/day
}
_DEFAULT_DAILY_MINUTES = 25  # fallback for unknown/unmapped bands (2-4h band)


def _daily_minutes_for_band(weekly_band: str) -> int:
    """Resolve a weekly time-band to a daily-minutes planning budget.

    Returns the documented mapping, falling back to the 2-4h default if the
    band is unknown (new option, typo, i18n drift) rather than refusing to
    onboard the student.
    """

    return _WEEKLY_BAND_DAILY_MINUTES.get(weekly_band.strip(), _DEFAULT_DAILY_MINUTES)


def _first_node_of_course(db: Session, course_id: UUID) -> KnowledgeNode | None:
    """Return the earliest node of a course for seeding the first path.

    Nodes are ordered by chapter ``sequence`` (the only governed ordering
    column) then by ``KnowledgeNode.id`` as a deterministic tiebreak within a
    chapter — the catalogue has no per-node ordering field, so the UUID
    tiebreak keeps the pick stable across runs. ``bootstrap.seed_demo_learning_
    data`` hardcodes this node; here we resolve it generically per course.
    """

    return db.scalar(
        select(KnowledgeNode)
        .where(KnowledgeNode.course_id == course_id)
        .join(CourseChapter, CourseChapter.id == KnowledgeNode.chapter_id)
        .order_by(CourseChapter.sequence, KnowledgeNode.id)
        .limit(1)
    )


def _has_current_path(db: Session, *, tenant_id: UUID, student_id: UUID, course_id: UUID) -> bool:
    """True if the student already owns a CURRENT path for this course."""

    return (
        db.scalar(
            select(LearningPath.id).where(
                LearningPath.tenant_id == tenant_id,
                LearningPath.student_id == student_id,
                LearningPath.course_id == course_id,
                LearningPath.status == LearningPathStatus.CURRENT,
            )
        )
        is not None
    )


def _compile_initial_path_for_student(
    db: Session,
    *,
    tenant_id: UUID,
    student_id: UUID,
    course_id: UUID,
    daily_minutes: int,
) -> ValidatedPath | None:
    """Compile the student's first learning path after onboarding (BE-018 fix).

    Mirrors ``bootstrap.seed_demo_learning_data``: pick the first node of the
    course (earliest chapter sequence, then node id), validate a single-step
    proposal, and persist it as version 1. Returns None if the course has no
    nodes (caller reports ``path_compiled=False`` without failing onboarding).

    Idempotency is enforced by ``persist_validated_path`` via the
    ``uq_learning_path_current`` partial unique index and the ``expected_version
    =0`` optimistic-concurrency check: if a CURRENT path already exists the
    persist call raises ``PathVersionConflict``, which callers are expected to
    have pre-empted with ``_has_current_path``.
    """

    first_node = _first_node_of_course(db, course_id)
    if first_node is None:
        return None
    validated = validate_path(
        PathProposal(steps=[StepProposal(node_id=first_node.id, estimated_minutes=20)]),
        ValidationContext(
            daily_minutes=max(1, daily_minutes),
            prerequisites={},
            completed_nodes=set(),
            due_reviews=[],
            mastery_policy_nodes={first_node.id},
            resource_ready_nodes={first_node.id},
            active_node_ids=set(),
            template_fallback_nodes=set(),
            forbidden_node_ids=set(),
        ),
    )
    persist_validated_path(
        db,
        tenant_id=tenant_id,
        student_id=student_id,
        course_id=course_id,
        expected_version=0,
        validated=validated,
    )
    return validated


@router.post(
    "/onboarding",
    status_code=status.HTTP_201_CREATED,
    response_model=OnboardingSubmissionView,
)
async def submit_onboarding(
    body: OnboardingSubmissionRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OnboardingSubmissionView | JSONResponse:
    """Record onboarding answers as evidence and project them (BE-018).

    The answers flow through the deterministic profile projection as a
    low-confidence INDEPENDENCE_SUPPORT baseline (never auto-advancing
    mastery). A path-replan request is emitted via the Outbox so the existing
    worker-driven compilation pipeline can re-evaluate eligibility later.

    V1.1 fix: that Outbox event currently has no consumer, so students would
    land on a "waiting for path compilation" empty state. To unblock them
    immediately we *also* synchronously compile the first single-step
    ``LearningPath`` right here (mirroring ``bootstrap.seed_demo_learning_
    data``), seeded from the first node of the canonical published course and
    budgeted from the self-reported ``weekly_band``. The replan event stays in
    place for future worker-driven expansion; the synchronous compile is what
    actually unblocks today/path/code-lab/KG/chat today.
    """

    _require_student_role(db, user)
    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    cached = begin_command(db, scope)
    if cached is not None:
        return JSONResponse(
            content=cached.response_body or {},
            status_code=cached.response_status or status.HTTP_201_CREATED,
        )

    trace_id = str(request.state.trace_id)
    answers_payload = body.answers.model_dump(mode="json")
    evidence_event_id = f"evt_onboarding_{uuid4().hex}"
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        evidence = record_evidence(
            db,
            tenant_id=user.tenant_id,
            student_id=user.id,
            event_id=evidence_event_id,
            event_type="ONBOARDING_RECORDED",
            trace_id=trace_id,
            payload=answers_payload,
            evidence_confidence=0.3,
        )
        if evidence is None:
            # The idempotency-key reservation should already prevent duplicate
            # event_ids; a collision here is a contract violation, not a retry.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="onboarding evidence already recorded",
            )
        profile = project_onboarding(
            db,
            tenant_id=user.tenant_id,
            student_id=user.id,
            source_event_id=evidence_event_id,
            expected_version=body.expected_profile_version,
            answers=answers_payload,
        )
        # Synchronously seed the student's first learning path so today/path/
        # code-lab/KG/chat are not blocked on a worker that doesn't exist yet.
        # Idempotent: skip if the student already owns a CURRENT path (onboarding
        # retried, or a path pre-existed from another flow) — never overwrite.
        course_id = _resolve_published_course_id(db)
        path_compiled = False
        if course_id is not None and not _has_current_path(
            db,
            tenant_id=user.tenant_id,
            student_id=user.id,
            course_id=course_id,
        ):
            daily_minutes = _daily_minutes_for_band(body.answers.weekly_band)
            compiled = _compile_initial_path_for_student(
                db,
                tenant_id=user.tenant_id,
                student_id=user.id,
                course_id=course_id,
                daily_minutes=daily_minutes,
            )
            path_compiled = compiled is not None
        view = OnboardingSubmissionView(
            evidence_event_id=evidence_event_id,
            profile_version_id=str(profile.id),
            profile_version=profile.version,
            replan_requested=True,
            path_compiled=path_compiled,
        )
        response_body = view.model_dump(mode="json")
        record_audit(
            db,
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            action="ONBOARDING_SUBMITTED",
            resource_type="profile_version",
            resource_id=str(profile.id),
            trace_id=trace_id,
            detail={"evidence_event_id": evidence_event_id},
        )
        uow.publish(
            event_type="PATH_REPLAN_REQUESTED",
            aggregate_type="profile_version",
            aggregate_id=str(profile.id),
            tenant_id=user.tenant_id,
            trace_id=trace_id,
            payload={
                "evidence_event_id": evidence_event_id,
                "source": "ONBOARDING",
                "weekly_band": body.answers.weekly_band,
            },
        )
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_201_CREATED,
            response_body=response_body,
        )
        uow.commit()
    return view
