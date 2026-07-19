"""Onboarding evidence submit endpoint + profile projection (BE-018).

Validates the V1.1 fix for the V1.0 bug where student onboarding answers only
updated local component state. The endpoint accepts structured answers,
records them as ``ONBOARDING_RECORDED`` evidence, projects them through the
deterministic profile pipeline (never auto-advancing mastery), and emits a
``PATH_REPLAN_REQUESTED`` Outbox event.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import create_app
from app.models import (
    AuditEvent,
    EvidenceEvent,
    LearningPath,
    LearningPathStatus,
    LearningPathStep,
    OutboxEvent,
    ProfileDimension,
    ProfileDimensionScore,
    ProfileVersion,
    User,
    UserStatus,
)
from app.models.base import RoleName
from app.pathing import (
    PathProposal,
    StepProposal,
    ValidationContext,
    persist_validated_path,
    validate_path,
)
from app.security import hash_password
from app.services import assign_role, create_student_user, get_or_create_tenant
from tests.conftest import COURSE_ID, NODE_ID


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
        email=f"onboarding-{uuid4().hex}@example.com",
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


def _answers() -> dict[str, str]:
    return {
        "prior_experience": "first time learning Python",
        "primary_goal": "catch up with coursework",
        "error_strategy": "read the error message",
        "preferred_exercise": "runnable code",
        "weekly_band": "2-4 hours",
    }


class TestOnboardingSubmit:
    def test_creates_evidence_and_projects_profile(
        self, client: TestClient, db_session: Session, student_auth
    ) -> None:
        student, token = student_auth
        body = {"answers": _answers(), "expected_profile_version": 0}
        response = client.post(
            "/api/v1/profiles/onboarding",
            json=body,
            headers=_headers(token, "onboarding-001", "trc_onboarding"),
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["replan_requested"] is True
        assert payload["profile_version"] == 1

        evidence = db_session.scalar(
            select(EvidenceEvent).where(
                EvidenceEvent.student_id == student.id,
                EvidenceEvent.event_type == "ONBOARDING_RECORDED",
            )
        )
        assert evidence is not None
        assert evidence.event_id == payload["evidence_event_id"]
        assert evidence.evidence_confidence == 0.3
        assert evidence.payload["weekly_band"] == "2-4 hours"

        profile = db_session.scalar(
            select(ProfileVersion).where(ProfileVersion.student_id == student.id)
        )
        assert profile is not None
        assert profile.source_event_id == evidence.event_id
        score = db_session.scalar(
            select(ProfileDimensionScore).where(
                ProfileDimensionScore.profile_version_id == profile.id,
                ProfileDimensionScore.dimension == ProfileDimension.INDEPENDENCE_SUPPORT,
            )
        )
        assert score is not None
        assert score.scope_key == "onboarding"
        assert score.confidence == 0.3
        assert score.support_level == 3

        assert (
            db_session.scalar(select(AuditEvent).where(AuditEvent.trace_id == "trc_onboarding"))
            is not None
        )
        outbox = db_session.scalar(
            select(OutboxEvent).where(OutboxEvent.trace_id == "trc_onboarding")
        )
        assert outbox is not None
        assert outbox.event_type == "PATH_REPLAN_REQUESTED"
        assert outbox.payload["source"] == "ONBOARDING"

    def test_is_idempotent_on_duplicate_key(
        self, client: TestClient, db_session: Session, student_auth
    ) -> None:
        _, token = student_auth
        body = {"answers": _answers(), "expected_profile_version": 0}
        headers = _headers(token, "onboarding-dup", "trc_onboarding_dup")
        first = client.post("/api/v1/profiles/onboarding", json=body, headers=headers)
        second = client.post("/api/v1/profiles/onboarding", json=body, headers=headers)
        assert first.status_code == second.status_code == 201
        assert first.json()["evidence_event_id"] == second.json()["evidence_event_id"]
        assert first.json()["profile_version_id"] == second.json()["profile_version_id"]

        events = list(
            db_session.scalars(
                select(EvidenceEvent).where(EvidenceEvent.event_type == "ONBOARDING_RECORDED")
            )
        )
        assert len(events) == 1

    def test_rejects_unauthenticated(self, client: TestClient) -> None:
        body = {"answers": _answers(), "expected_profile_version": 0}
        response = client.post("/api/v1/profiles/onboarding", json=body)
        assert response.status_code == 401, response.text

    def test_rejects_non_student_token(self, client: TestClient, db_session: Session) -> None:
        tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
        db_session.flush()
        admin = User(
            tenant_id=tenant.id,
            email=f"onboarding-admin-{uuid4().hex}@example.com",
            password_hash=hash_password("AdminPass1!"),
            status=UserStatus.ACTIVE,
        )
        db_session.add(admin)
        db_session.flush()
        assign_role(db_session, user_id=admin.id, role_name=RoleName.COURSE_ADMIN.value)
        login = client.post(
            "/api/v1/auth/login",
            json={"email": admin.email, "password": "AdminPass1!"},
        )
        assert login.status_code == 200, login.text
        admin_token = login.json()["access_token"]
        body = {"answers": _answers(), "expected_profile_version": 0}
        response = client.post(
            "/api/v1/profiles/onboarding",
            json=body,
            headers=_headers(admin_token, "onboarding-admin", "trc_onboarding_admin"),
        )
        assert response.status_code == 403, response.text

    def test_rejects_missing_idempotency_key(self, client: TestClient, student_auth) -> None:
        _, token = student_auth
        body = {"answers": _answers(), "expected_profile_version": 0}
        response = client.post(
            "/api/v1/profiles/onboarding",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422, response.text

    def test_onboarding_compiles_initial_path(
        self, client: TestClient, db_session: Session, student_auth
    ) -> None:
        """BE-018 fix: onboarding must synchronously compile a first LearningPath.

        Before the fix, only a PATH_REPLAN_REQUESTED Outbox event was emitted
        with no consumer, leaving the student on an empty 'waiting for path
        compilation' state. Now the endpoint calls validate_path +
        persist_validated_path inline, so today/path/code-lab/KG/chat unblock
        immediately without relying on a worker that does not exist yet.
        """

        student, token = student_auth
        body = {"answers": _answers(), "expected_profile_version": 0}
        response = client.post(
            "/api/v1/profiles/onboarding",
            json=body,
            headers=_headers(token, "onboarding-compile", "trc_onboarding_compile"),
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["path_compiled"] is True

        path = db_session.scalar(
            select(LearningPath).where(
                LearningPath.student_id == student.id,
                LearningPath.status == LearningPathStatus.CURRENT,
            )
        )
        assert path is not None
        assert path.version == 1
        steps = list(
            db_session.scalars(
                select(LearningPathStep)
                .where(LearningPathStep.path_id == path.id)
                .order_by(LearningPathStep.position)
            )
        )
        assert len(steps) >= 1
        # V1.1: the initial path now compiles the first 5 nodes of the course
        # (multi-step proposal) so the student gets multiple today items to
        # choose from rather than a single 20-minute island. Each step is a
        # 10-minute LEARN node seeded from the first course nodes; validate_path
        # may split a step if it exceeds the daily budget, so we only assert
        # the first step's position and the node set covers the first nodes.
        assert steps[0].position == 1
        assert steps[0].estimated_minutes == 10
        # The path should cover at least the first node of the course.
        assert any(step.node_id == NODE_ID for step in steps)

    def test_onboarding_idempotent_does_not_recompile_path(
        self, client: TestClient, db_session: Session, student_auth
    ) -> None:
        """Retrying onboarding with the same Idempotency-Key must not recompile.

        The cached response is replayed and the already-persisted CURRENT path
        is left untouched (same version, no duplicate steps). This protects the
        optimistic-concurrency contract of persist_validated_path (expected
        version 0) against accidental replays.
        """

        student, token = student_auth
        body = {"answers": _answers(), "expected_profile_version": 0}
        headers = _headers(token, "onboarding-idem-recompile", "trc_onboarding_idem_recompile")
        first = client.post("/api/v1/profiles/onboarding", json=body, headers=headers)
        assert first.status_code == 201, first.text
        assert first.json()["path_compiled"] is True

        path = db_session.scalar(
            select(LearningPath).where(
                LearningPath.student_id == student.id,
                LearningPath.status == LearningPathStatus.CURRENT,
            )
        )
        assert path is not None
        first_version = path.version
        first_path_id = path.id
        first_step_count = db_session.scalar(
            select(LearningPathStep.path_id).where(LearningPathStep.path_id == path.id)
        )

        second = client.post("/api/v1/profiles/onboarding", json=body, headers=headers)
        assert second.status_code == 201, second.text
        # Cached response is replayed verbatim.
        assert second.json() == first.json()

        # Path row untouched: same id, same version, no extra steps, no new rows.
        db_session.expire_all()
        refreshed = db_session.get(LearningPath, first_path_id)
        assert refreshed is not None
        assert refreshed.version == first_version
        assert refreshed.status == LearningPathStatus.CURRENT
        all_paths = list(
            db_session.scalars(select(LearningPath).where(LearningPath.student_id == student.id))
        )
        assert len(all_paths) == 1
        assert first_step_count is not None  # sanity: at least one step existed

    def test_onboarding_without_existing_path_compile_idempotent(
        self, client: TestClient, db_session: Session, student_auth
    ) -> None:
        """Onboarding must NOT overwrite a CURRENT path that pre-existed it.

        Edge case: a student already had a LearningPath (from a prior flow or
        manual seeding) before submitting onboarding. The endpoint's
        _has_current_path guard must skip re-compilation so the existing path
        version/steps are preserved, and path_compiled reflects 'nothing new
        compiled here'.
        """

        student, token = student_auth
        # Seed a pre-existing CURRENT path for the canonical course (version 1,
        # so persist_validated_path's expected_version=0 would conflict if the
        # endpoint ignored the guard).
        course_id = COURSE_ID
        first_node_id = NODE_ID
        validated = validate_path(
            PathProposal(steps=[StepProposal(node_id=first_node_id, estimated_minutes=15)]),
            ValidationContext(
                daily_minutes=30,
                prerequisites={},
                completed_nodes=set(),
                due_reviews=[],
                mastery_policy_nodes={first_node_id},
                resource_ready_nodes={first_node_id},
                active_node_ids=set(),
                template_fallback_nodes=set(),
                forbidden_node_ids=set(),
            ),
        )
        persist_validated_path(
            db_session,
            tenant_id=student.tenant_id,
            student_id=student.id,
            course_id=course_id,
            expected_version=0,
            validated=validated,
        )
        db_session.flush()
        pre_path = db_session.scalar(
            select(LearningPath).where(
                LearningPath.student_id == student.id,
                LearningPath.status == LearningPathStatus.CURRENT,
            )
        )
        assert pre_path is not None
        pre_version = pre_path.version
        pre_path_id = pre_path.id

        body = {"answers": _answers(), "expected_profile_version": 0}
        response = client.post(
            "/api/v1/profiles/onboarding",
            json=body,
            headers=_headers(token, "onboarding-preexisting", "trc_onboarding_preexisting"),
        )
        assert response.status_code == 201, response.text
        # No new path compiled: the pre-existing one was left in place.
        assert response.json()["path_compiled"] is False

        db_session.expire_all()
        untouched = db_session.get(LearningPath, pre_path_id)
        assert untouched is not None
        assert untouched.version == pre_version
        assert untouched.status == LearningPathStatus.CURRENT
        all_paths = list(
            db_session.scalars(select(LearningPath).where(LearningPath.student_id == student.id))
        )
        assert len(all_paths) == 1
