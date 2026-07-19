"""BE-027 minimal course CMS API tests.

Scope: V1.0 seeds the catalogue from a frozen JSON file with no editing
surface. The CMS gives Course/System Admins a minimal, audited way to edit
knowledge nodes and question templates. Validation MUST reuse
``knowledge_assets.validate_course_document`` — an invalid edit cannot
publish — and every successful write/publish records an ``AuditEvent``.

Versioning decision (documented in ``app/api/cms.py``): V1.1 keeps scope
minimal — there is no separate staging table. A PUT validates the full
synthetic bundle (the node replaced by the proposed shape) via the existing
doc-level validator, applies the change to the published row in the same
transaction, and writes an ``AuditEvent``. POST publish is the explicit,
audit-confirmed commit step. A staging table + version-control flow is
deferred to a later slice.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.knowledge_seed import seed_published_course
from app.main import create_app
from app.models import KnowledgeNode, KnowledgeQuestionTemplate
from app.models.base import RoleName, UserStatus
from app.models.consistency import AuditEvent
from app.models.identity import User
from app.security import hash_password
from app.services import assign_role, create_student_user, get_or_create_tenant

COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
NODE_ID = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")
QUESTION_ID = UUID("f294238b-386d-58f2-bfd8-3e644b3e329d")


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client: TestClient, email: str, password: str) -> str:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    token: str = resp.json()["access_token"]
    return token


def _make_course_admin(db_session: Session, email: str = "cms-admin@uni.edu") -> User:
    """Create an ACTIVE Course Admin user scoped to the default tenant."""
    tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
    db_session.flush()
    admin = User(
        tenant_id=tenant.id,
        email=email,
        password_hash=hash_password("AdminPass1!"),
        status=UserStatus.ACTIVE,
        display_name="CMS Admin",
    )
    db_session.add(admin)
    db_session.flush()
    assign_role(db_session, user_id=admin.id, role_name=RoleName.COURSE_ADMIN.value)
    return admin


def _ensure_course_seeded(db_session: Session) -> None:
    """The default db_session fixture seeds the canonical course; assert it."""
    if db_session.get(KnowledgeNode, NODE_ID) is None:
        seed_published_course(db_session)
        db_session.flush()


# --------------------------------------------------------------------------- #
# GET nodes (list)
# --------------------------------------------------------------------------- #
class TestListNodes:
    def test_list_nodes_returns_paginated_chapter_ordered_rows(
        self, client: TestClient, db_session: Session
    ) -> None:
        _ensure_course_seeded(db_session)
        _make_course_admin(db_session)
        token = _login(client, "cms-admin@uni.edu", "AdminPass1!")

        resp = client.get(
            "/api/v1/admin/cms/nodes?page=1&page_size=5",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["items"]
        assert len(body["items"]) <= 5
        # Every item surfaces the editable-locator fields.
        for item in body["items"]:
            for field in (
                "node_id",
                "course_id",
                "chapter_id",
                "chapter_title",
                "title",
                "content_version",
            ):
                assert field in item
            assert item["chapter_title"]
            assert item["title"]
        # Pagination metadata reflects the full canonical course.
        meta = body["page"]
        assert meta["page"] == 1
        assert meta["page_size"] == 5
        assert meta["total_items"] == 93
        assert meta["total_pages"] == 19  # ceil(93 / 5)

    def test_list_nodes_supports_title_substring_search(
        self, client: TestClient, db_session: Session
    ) -> None:
        _ensure_course_seeded(db_session)
        _make_course_admin(db_session)
        token = _login(client, "cms-admin@uni.edu", "AdminPass1!")

        # First fetch a known title to search for, then verify the filter narrows.
        seeded = client.get(
            "/api/v1/admin/cms/nodes?page=1&page_size=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert seeded.status_code == 200, seeded.text
        known_title = seeded.json()["items"][0]["title"]
        # Use a unique substring unlikely to collide across all 93 nodes.
        needle = known_title[:3]

        filtered = client.get(
            f"/api/v1/admin/cms/nodes?q={needle}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert filtered.status_code == 200, filtered.text
        body = filtered.json()
        assert body["page"]["total_items"] >= 1
        assert body["page"]["total_items"] < 93
        for item in body["items"]:
            assert needle.lower() in item["title"].lower()

    def test_list_nodes_rejects_non_admin(self, client: TestClient, db_session: Session) -> None:
        _ensure_course_seeded(db_session)
        # No admin user created → only the course is seeded.
        resp = client.get("/api/v1/admin/cms/nodes")
        assert resp.status_code == 401

    def test_list_nodes_rejects_empty_query(self, client: TestClient, db_session: Session) -> None:
        _ensure_course_seeded(db_session)
        _make_course_admin(db_session)
        token = _login(client, "cms-admin@uni.edu", "AdminPass1!")

        resp = client.get(
            "/api/v1/admin/cms/nodes?q=",
            headers={"Authorization": f"Bearer {token}"},
        )
        # min_length=1 on the Query param makes FastAPI return 422.
        assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# GET node
# --------------------------------------------------------------------------- #
class TestGetNode:
    def test_get_node_returns_full_editable_shape(
        self, client: TestClient, db_session: Session
    ) -> None:
        _ensure_course_seeded(db_session)
        _make_course_admin(db_session)
        token = _login(client, "cms-admin@uni.edu", "AdminPass1!")

        resp = client.get(
            f"/api/v1/admin/cms/nodes/{NODE_ID}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["node_id"] == str(NODE_ID)
        # Editable surface must surface every field the PUT can later update.
        for field in (
            "title",
            "learning_objectives",
            "prerequisites",
            "misconceptions",
            "examples",
            "diagnostic_items",
            "practice_templates",
            "source_ids",
            "content_version",
        ):
            assert field in body, f"missing editable field {field}"
        assert body["title"]  # canonical node has a non-empty title

    def test_get_unknown_node_returns_404(self, client: TestClient, db_session: Session) -> None:
        _ensure_course_seeded(db_session)
        _make_course_admin(db_session)
        token = _login(client, "cms-admin@uni.edu", "AdminPass1!")
        unknown = UUID("00000000-0000-4000-8000-000000000099")
        resp = client.get(
            f"/api/v1/admin/cms/nodes/{unknown}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# PUT node — validate + apply + audit
# --------------------------------------------------------------------------- #
class TestPutNode:
    def test_put_node_updates_fields_and_writes_audit(
        self, client: TestClient, db_session: Session
    ) -> None:
        _ensure_course_seeded(db_session)
        admin = _make_course_admin(db_session)
        token = _login(client, "cms-admin@uni.edu", "AdminPass1!")

        before = db_session.get(KnowledgeNode, NODE_ID)
        assert before is not None
        original_title = before.title
        original_version = str(before.content_version)

        new_title = "[CMS] 解释器与交互模式（修订）"
        resp = client.put(
            f"/api/v1/admin/cms/nodes/{NODE_ID}",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "cms-node-edit-1",
                "x-trace-id": "trc_cms_put",
            },
            json={
                "title": new_title,
                "learning_objectives": ["区分交互命令和脚本执行（修订）"],
                "misconceptions": ["终端会自动理解 Python 语法（修订）"],
                "examples": [">>> 1 + 2", ">>> print('hi')"],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["title"] == new_title
        assert body["learning_objectives"] == ["区分交互命令和脚本执行（修订）"]
        # content_version must advance — published edits must not be silent.
        assert body["content_version"] != original_version

        # Subsequent GET reflects the edit.
        follow = client.get(
            f"/api/v1/admin/cms/nodes/{NODE_ID}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert follow.status_code == 200
        assert follow.json()["title"] == new_title

        # Audit row written with the editor and a publish/commit marker.
        audit = db_session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_type == "knowledge_node",
                AuditEvent.resource_id == str(NODE_ID),
            )
        )
        assert audit is not None
        assert audit.actor_user_id == admin.id
        assert audit.trace_id == "trc_cms_put"
        assert audit.detail.get("source") == "CMS"
        # Payload digest is redacted, not the raw payload.
        assert "digest" in audit.detail
        assert audit.detail["digest"] != new_title

        # Roll back the title so other tests in the session stay deterministic.
        before.title = original_title
        before.content_version = original_version
        db_session.flush()

    def test_put_node_rejects_invalid_payload_and_writes_no_audit(
        self, client: TestClient, db_session: Session
    ) -> None:
        _ensure_course_seeded(db_session)
        _make_course_admin(db_session)
        token = _login(client, "cms-admin@uni.edu", "AdminPass1!")

        node = db_session.get(KnowledgeNode, NODE_ID)
        assert node is not None
        original_title = node.title
        original_version = node.content_version

        # Empty title is rejected by the asset contract (NonEmptyText).
        resp = client.put(
            f"/api/v1/admin/cms/nodes/{NODE_ID}",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "cms-node-invalid-1",
            },
            json={"title": ""},
        )
        assert 400 <= resp.status_code < 500, resp.text

        # Node unchanged.
        unchanged = db_session.get(KnowledgeNode, NODE_ID)
        assert unchanged is not None
        assert unchanged.title == original_title
        assert unchanged.content_version == original_version

        audit = db_session.scalar(select(AuditEvent).where(AuditEvent.resource_id == str(NODE_ID)))
        assert audit is None


# --------------------------------------------------------------------------- #
# POST publish — explicit audit-confirmed commit
# --------------------------------------------------------------------------- #
class TestPublishNode:
    def test_publish_records_publish_marker_audit(
        self, client: TestClient, db_session: Session
    ) -> None:
        _ensure_course_seeded(db_session)
        admin = _make_course_admin(db_session)
        token = _login(client, "cms-admin@uni.edu", "AdminPass1!")

        resp = client.post(
            f"/api/v1/admin/cms/nodes/{NODE_ID}/publish",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "cms-node-publish-1",
                "x-trace-id": "trc_cms_publish",
            },
            json={"notes": "Confirm quarterly review release."},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["node_id"] == str(NODE_ID)
        assert body["published"] is True
        assert body["content_version"]

        audit = db_session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "CMS_NODE_PUBLISHED",
                AuditEvent.resource_id == str(NODE_ID),
            )
        )
        assert audit is not None
        assert audit.actor_user_id == admin.id
        assert audit.trace_id == "trc_cms_publish"
        assert audit.detail.get("source") == "CMS"

    def test_publish_unknown_node_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        _ensure_course_seeded(db_session)
        _make_course_admin(db_session)
        token = _login(client, "cms-admin@uni.edu", "AdminPass1!")
        unknown = UUID("00000000-0000-4000-8000-000000000099")
        resp = client.post(
            f"/api/v1/admin/cms/nodes/{unknown}/publish",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "cms-node-publish-unknown",
            },
            json={"notes": "x"},
        )
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Question template PUT + publish
# --------------------------------------------------------------------------- #
class TestQuestionTemplate:
    def test_put_question_updates_prompt_and_audits(
        self, client: TestClient, db_session: Session
    ) -> None:
        _ensure_course_seeded(db_session)
        admin = _make_course_admin(db_session)
        token = _login(client, "cms-admin@uni.edu", "AdminPass1!")

        qt = db_session.get(KnowledgeQuestionTemplate, QUESTION_ID)
        assert qt is not None
        original_prompt = qt.prompt_template
        original_version = str(qt.content_version)

        new_prompt = "[CMS] 关于「解释器与交互模式」，下列哪项分析符合 Python 语义？（修订）"
        resp = client.put(
            f"/api/v1/admin/cms/question_templates/{QUESTION_ID}",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "cms-q-edit-1",
                "x-trace-id": "trc_cms_qput",
            },
            json={"prompt_template": new_prompt},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["prompt_template"] == new_prompt

        audit = db_session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_type == "knowledge_question_template",
                AuditEvent.resource_id == str(QUESTION_ID),
            )
        )
        assert audit is not None
        assert audit.actor_user_id == admin.id
        assert audit.trace_id == "trc_cms_qput"
        assert audit.detail.get("source") == "CMS"

        # Restore for other tests.
        qt.prompt_template = original_prompt
        qt.content_version = original_version
        db_session.flush()

    def test_publish_question_records_publish_marker(
        self, client: TestClient, db_session: Session
    ) -> None:
        _ensure_course_seeded(db_session)
        admin = _make_course_admin(db_session)
        token = _login(client, "cms-admin@uni.edu", "AdminPass1!")

        resp = client.post(
            f"/api/v1/admin/cms/question_templates/{QUESTION_ID}/publish",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "cms-q-publish-1",
                "x-trace-id": "trc_cms_qpub",
            },
            json={"notes": "Confirm quarterly review release."},
        )
        assert resp.status_code == 200, resp.text
        audit = db_session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "CMS_QUESTION_PUBLISHED",
                AuditEvent.resource_id == str(QUESTION_ID),
            )
        )
        assert audit is not None
        assert audit.actor_user_id == admin.id
        assert audit.trace_id == "trc_cms_qpub"


# --------------------------------------------------------------------------- #
# Auth matrix
# --------------------------------------------------------------------------- #
class TestCmsAuth:
    def test_unauthenticated_request_rejected(
        self, client: TestClient, db_session: Session
    ) -> None:
        _ensure_course_seeded(db_session)
        resp = client.get(f"/api/v1/admin/cms/nodes/{NODE_ID}")
        assert resp.status_code == 401

    def test_student_token_rejected(self, client: TestClient, db_session: Session) -> None:
        _ensure_course_seeded(db_session)
        tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
        db_session.flush()
        student = create_student_user(
            db_session,
            tenant_id=tenant.id,
            email="cms-student@example.com",
            password_hash=hash_password("ValidPass1!"),
        )
        student.status = UserStatus.ACTIVE
        db_session.flush()

        token = _login(client, "cms-student@example.com", "ValidPass1!")
        resp = client.get(
            f"/api/v1/admin/cms/nodes/{NODE_ID}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_non_course_admin_staff_rejected(self, client: TestClient, db_session: Session) -> None:
        """Reviewer is staff but must NOT edit course content."""
        _ensure_course_seeded(db_session)
        tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
        db_session.flush()
        reviewer = User(
            tenant_id=tenant.id,
            email="cms-reviewer@uni.edu",
            password_hash=hash_password("ValidPass1!"),
            status=UserStatus.ACTIVE,
            display_name="Reviewer",
        )
        db_session.add(reviewer)
        db_session.flush()
        assign_role(db_session, user_id=reviewer.id, role_name=RoleName.REVIEWER.value)

        token = _login(client, "cms-reviewer@uni.edu", "ValidPass1!")
        resp = client.get(
            f"/api/v1/admin/cms/nodes/{NODE_ID}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_system_admin_can_access(self, client: TestClient, db_session: Session) -> None:
        _ensure_course_seeded(db_session)
        # System Admin is in COURSE_ADMIN_ROLES, so CMS is reachable.
        tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
        db_session.flush()
        sysadmin = User(
            tenant_id=tenant.id,
            email="cms-sysadmin@uni.edu",
            password_hash=hash_password("ValidPass1!"),
            status=UserStatus.ACTIVE,
            display_name="Sys Admin",
        )
        db_session.add(sysadmin)
        db_session.flush()
        assign_role(db_session, user_id=sysadmin.id, role_name=RoleName.SYSTEM_ADMIN.value)

        token = _login(client, "cms-sysadmin@uni.edu", "ValidPass1!")
        resp = client.get(
            f"/api/v1/admin/cms/nodes/{NODE_ID}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
