"""BE-005 Task 8 student code/submission/cancel/hint API integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.code import get_sandbox_client, get_session_factory
from app.contracts.sandbox import (
    CodeRunStatus,
    SandboxResult,
    SandboxRunStatus,
)
from app.db import get_db
from app.main import create_app
from app.models import (
    TaskDefinition,
    TaskInstance,
    User,
    UserStatus,
)
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant
from app.task_compiler import CompileInput, compile_task_version, start_task_instance

COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
NODE_ID = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")
NOW = datetime(2026, 7, 17, 9, 0, tzinfo=UTC)


def _snapshot() -> dict[str, Any]:
    return {
        "prompt": "Return the sum.",
        "tests_policy": {
            "entrypoint": {"kind": "FUNCTION", "name": "solve"},
            "allowed_imports": ["math"],
            "visible": [
                {
                    "id": "visible-basic",
                    "args": [[1, 2]],
                    "expected": 3,
                    "comparison": "EQUAL",
                    "transfer": False,
                }
            ],
            "hidden": [
                {
                    "id": "hidden-transfer",
                    "args": [[0, 0]],
                    "expected": 0,
                    "comparison": "EQUAL",
                    "transfer": True,
                }
            ],
        },
        "hint_policy": {
            "max_level": 2,
            "hints": [
                {
                    "key": "inspect-input",
                    "level": 1,
                    "content": "Inspect the input shape.",
                    "independence_cost": 10,
                },
                {
                    "key": "check-bound",
                    "level": 2,
                    "content": "Check the boundary.",
                    "independence_cost": 25,
                },
            ],
        },
        "mastery_policy": {},
        "resource_versions": {},
        "scenario_key": "sum-v1",
    }


class FakeSandbox:
    def __init__(
        self,
        *,
        visible: SandboxResult | None = None,
        hidden: SandboxResult | None = None,
    ) -> None:
        self.visible = visible
        self.hidden = hidden
        self.execute_calls: list[str] = []
        self.cancel_calls: list[str] = []

    def execute_phase(self, request: Any) -> SandboxResult:
        phase = request.phase.value
        self.execute_calls.append(phase)
        if phase == "VISIBLE":
            assert self.visible is not None
            return self.visible.model_copy(update={"run_id": request.run_id})
        assert self.hidden is not None
        return self.hidden.model_copy(update={"run_id": request.run_id})

    def cancel(self, run_id: str) -> bool:
        self.cancel_calls.append(run_id)
        return True


def _passed(run_id: str = "x", *, hidden: bool = False, passed: bool = True) -> SandboxResult:
    return SandboxResult(
        run_id=run_id,
        status=SandboxRunStatus.PASSED if passed else SandboxRunStatus.FAILED,
        passed=passed,
        stdout="",
        stderr="",
        tests=[
            {
                "case_id": "hidden-1" if hidden else "visible-basic",
                "display_name": "hidden-1" if hidden else "visible-basic",
                "visibility": "HIDDEN" if hidden else "VISIBLE",
                "comparison": "EQUAL",
                "transfer": hidden,
                "passed": passed,
                "stdout": "",
                "stderr": "",
                "duration_ms": 4,
            }
        ],
        trace_frames=None,
        resource_usage={"cpu_ms": 1, "wall_ms": 1, "peak_memory_kb": 100, "exit_code": 0},
        stdout_truncated=False,
        stderr_truncated=False,
        trace_truncated=False,
        user_error=None,
        platform_error=None,
    )


def _platform_failure(run_id: str = "x") -> SandboxResult:
    return SandboxResult.platform_failure(run_id=run_id, category="X", message="m")


@pytest.fixture()
def client(db_session: Session) -> Iterator[tuple[TestClient, FakeSandbox]]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    def _override_session_factory() -> Any:
        # Return a callable that yields the test's savepoint-bound session so
        # the orchestrator's three-transaction flow is visible to assertions.
        class _Factory:
            def __call__(self) -> Session:
                return db_session

        return _Factory()

    fake = FakeSandbox(visible=_passed(), hidden=_passed(hidden=True))
    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_sandbox_client] = lambda: fake
    app.dependency_overrides[get_session_factory] = _override_session_factory
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client, fake
    app.dependency_overrides.clear()


def _auth(client: TestClient, db_session: Session) -> tuple[User, str]:
    tenant = get_or_create_tenant(db_session, slug="default", name="Default")
    db_session.flush()
    password = "ValidPass1!"
    user = create_student_user(
        db_session,
        tenant_id=tenant.id,
        email=f"code-api-{uuid4().hex}@example.com",
        password_hash=hash_password(password),
    )
    user.status = UserStatus.ACTIVE
    db_session.flush()
    response = client.post("/api/v1/auth/login", json={"email": user.email, "password": password})
    assert response.status_code == 200, response.text
    return user, response.json()["access_token"]


def _start_task(db_session: Session, user: User) -> TaskInstance:
    definition = TaskDefinition(
        tenant_id=user.tenant_id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        key=f"sum-{uuid4().hex}",
        title="Sum task",
    )
    db_session.add(definition)
    db_session.flush()
    snapshot = _snapshot()
    version = compile_task_version(
        db_session,
        definition,
        CompileInput(
            prompt=snapshot["prompt"],
            tests_policy=snapshot["tests_policy"],
            hint_policy=snapshot["hint_policy"],
            mastery_policy=snapshot["mastery_policy"],
            resource_versions=snapshot["resource_versions"],
            scenario_key=snapshot["scenario_key"],
        ),
    )
    db_session.flush()
    instance = start_task_instance(
        db_session,
        task_version_id=version.id,
        student_id=user.id,
        active_key=f"code-api-{uuid4().hex}",
    )
    db_session.flush()
    return instance


def _headers(token: str, key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key}


# --------------------------------------------------------------------------- #
# POST /api/v1/code/runs
# --------------------------------------------------------------------------- #


def test_run_is_idempotent_and_completes(
    client: tuple[TestClient, FakeSandbox], db_session: Session
) -> None:
    test_client, fake = client
    user, token = _auth(test_client, db_session)
    task = _start_task(db_session, user)
    body = {
        "task_instance_id": str(task.id),
        "source_code": "def solve(values):\n    return sum(values)\n",
        "mode": "RUN",
        "expected_task_version": task.version,
    }
    headers = _headers(token, "run-1")
    first = test_client.post("/api/v1/code/runs", json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == CodeRunStatus.COMPLETED.value
    assert fake.execute_calls == ["VISIBLE"]
    # Replay returns the same run_id.
    replay = test_client.post("/api/v1/code/runs", json=body, headers=headers)
    assert replay.status_code == 200
    assert replay.json()["run_id"] == first.json()["run_id"]
    assert len(fake.execute_calls) == 1


def test_run_requires_idempotency_key(
    client: tuple[TestClient, FakeSandbox], db_session: Session
) -> None:
    test_client, _ = client
    user, token = _auth(test_client, db_session)
    task = _start_task(db_session, user)
    body = {
        "task_instance_id": str(task.id),
        "source_code": "def solve(values):\n    return sum(values)\n",
        "mode": "RUN",
        "expected_task_version": task.version,
    }
    response = test_client.post(
        "/api/v1/code/runs",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code in {400, 409, 422}


def test_run_rejects_wrong_task_version(
    client: tuple[TestClient, FakeSandbox], db_session: Session
) -> None:
    test_client, _ = client
    user, token = _auth(test_client, db_session)
    task = _start_task(db_session, user)
    body = {
        "task_instance_id": str(task.id),
        "source_code": "def solve(values):\n    return sum(values)\n",
        "mode": "RUN",
        "expected_task_version": task.version + 999,
    }
    response = test_client.post(
        "/api/v1/code/runs", json=body, headers=_headers(token, "bad-version")
    )
    assert response.status_code == 409


# --------------------------------------------------------------------------- #
# POST /api/v1/code/submissions
# --------------------------------------------------------------------------- #


def test_submission_runs_visible_and_hidden_and_emits_evidence(
    client: tuple[TestClient, FakeSandbox], db_session: Session
) -> None:
    test_client, fake = client
    user, token = _auth(test_client, db_session)
    task = _start_task(db_session, user)
    body = {
        "task_instance_id": str(task.id),
        "source_code": "def solve(values):\n    return sum(values)\n",
        "expected_task_version": task.version,
    }
    response = test_client.post(
        "/api/v1/code/submissions", json=body, headers=_headers(token, "submit-1")
    )
    assert response.status_code == 200, response.text
    assert fake.execute_calls == ["VISIBLE", "HIDDEN"]
    evidence_id = response.json()["evidence_event_id"]
    assert evidence_id is not None


def test_submission_platform_error_suppresses_evidence(
    client: tuple[TestClient, FakeSandbox], db_session: Session
) -> None:
    test_client, fake = client
    fake.hidden = _platform_failure()
    user, token = _auth(test_client, db_session)
    task = _start_task(db_session, user)
    body = {
        "task_instance_id": str(task.id),
        "source_code": "def solve(values):\n    return sum(values)\n",
        "expected_task_version": task.version,
    }
    response = test_client.post(
        "/api/v1/code/submissions", json=body, headers=_headers(token, "submit-plat")
    )
    assert response.status_code == 200
    assert response.json()["status"] == CodeRunStatus.PLATFORM_ERROR.value
    assert response.json()["evidence_event_id"] is None


# --------------------------------------------------------------------------- #
# GET /api/v1/code/runs/{run_id}
# --------------------------------------------------------------------------- #


def test_get_run_returns_student_scoped_view(
    client: tuple[TestClient, FakeSandbox], db_session: Session
) -> None:
    test_client, _ = client
    user, token = _auth(test_client, db_session)
    task = _start_task(db_session, user)
    body = {
        "task_instance_id": str(task.id),
        "source_code": "def solve(values):\n    return sum(values)\n",
        "mode": "RUN",
        "expected_task_version": task.version,
    }
    created = test_client.post("/api/v1/code/runs", json=body, headers=_headers(token, "get-1"))
    run_id = created.json()["run_id"]
    fetched = test_client.get(
        f"/api/v1/code/runs/{run_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == run_id


def test_get_run_returns_404_for_unknown_id(
    client: tuple[TestClient, FakeSandbox], db_session: Session
) -> None:
    test_client, _ = client
    _, token = _auth(test_client, db_session)
    response = test_client.get(
        "/api/v1/code/runs/run_doesnotexist00000000000000000000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# POST /api/v1/tasks/{task_instance_id}/hints
# --------------------------------------------------------------------------- #


def test_hint_level_1_succeeds(client: tuple[TestClient, FakeSandbox], db_session: Session) -> None:
    test_client, _ = client
    user, token = _auth(test_client, db_session)
    task = _start_task(db_session, user)
    body = {"level": 1, "expected_task_version": task.version}
    ok = test_client.post(
        f"/api/v1/tasks/{task.id}/hints", json=body, headers=_headers(token, "hint-1")
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["level"] == 1
    assert ok.json()["hint_key"] == "inspect-input"


def test_hint_skipping_level_is_rejected(
    client: tuple[TestClient, FakeSandbox], db_session: Session
) -> None:
    test_client, _ = client
    user, token = _auth(test_client, db_session)
    task = _start_task(db_session, user)
    # Requesting level 2 before level 1 must fail.
    body = {"level": 2, "expected_task_version": task.version}
    response = test_client.post(
        f"/api/v1/tasks/{task.id}/hints", json=body, headers=_headers(token, "hint-skip")
    )
    assert response.status_code == 409


def test_hint_replay_returns_same_usage(
    client: tuple[TestClient, FakeSandbox], db_session: Session
) -> None:
    test_client, _ = client
    user, token = _auth(test_client, db_session)
    task = _start_task(db_session, user)
    body = {"level": 1, "expected_task_version": task.version}
    first = test_client.post(
        f"/api/v1/tasks/{task.id}/hints", json=body, headers=_headers(token, "hint-replay")
    )
    assert first.status_code == 200, first.text
    replay = test_client.post(
        f"/api/v1/tasks/{task.id}/hints", json=body, headers=_headers(token, "hint-replay")
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first.json()["id"]
