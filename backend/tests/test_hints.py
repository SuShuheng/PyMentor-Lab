"""BE-005 deterministic, ordered static hint policy."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.code_runs import create_revision
from app.hints import InvalidHintRequest, record_hint_usage
from app.models import (
    TaskDefinition,
    TaskInstance,
    TaskInstanceStatus,
    TaskVersion,
    Tenant,
    User,
    UserStatus,
)

NOW = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)


@pytest.fixture()
def hint_task(db_session: Session) -> tuple[TaskInstance, User]:
    suffix = uuid4().hex
    tenant = Tenant(slug=f"hint-{suffix}", name="Hint Policy")
    db_session.add(tenant)
    db_session.flush()
    student = User(
        tenant_id=tenant.id,
        email=f"hint-{suffix}@example.com",
        password_hash="not-used",
        status=UserStatus.ACTIVE,
    )
    db_session.add(student)
    db_session.flush()
    definition = TaskDefinition(
        tenant_id=tenant.id,
        course_id=uuid4(),
        node_id=uuid4(),
        key=f"hint-{suffix}",
        title="Hint task",
    )
    db_session.add(definition)
    db_session.flush()
    snapshot = {
        "tests_policy": {
            "entrypoint": {"kind": "FUNCTION", "name": "solve"},
            "allowed_imports": [],
            "visible": [],
            "hidden": [],
        },
        "hint_policy": {
            "max_level": 2,
            "hints": [
                {
                    "key": "first",
                    "level": 1,
                    "content": "First hint.",
                    "independence_cost": 10,
                },
                {
                    "key": "second",
                    "level": 2,
                    "content": "Second hint.",
                    "independence_cost": 25,
                },
            ],
        },
    }
    version = TaskVersion(
        tenant_id=tenant.id,
        definition_id=definition.id,
        version=1,
        snapshot=snapshot,
        snapshot_digest="b" * 64,
        scenario_key="hint-v1",
        published=True,
        published_at=NOW,
    )
    db_session.add(version)
    db_session.flush()
    task = TaskInstance(
        tenant_id=tenant.id,
        student_id=student.id,
        task_version_id=version.id,
        active_key=f"hint-{suffix}",
        status=TaskInstanceStatus.ACTIVE,
        snapshot=snapshot,
        snapshot_digest=version.snapshot_digest,
        version=1,
    )
    db_session.add(task)
    db_session.flush()
    return task, student


def test_hints_must_be_requested_in_order_and_within_budget(
    db_session: Session, hint_task: tuple[TaskInstance, User]
) -> None:
    task, student = hint_task
    revision = create_revision(
        db_session,
        tenant_id=task.tenant_id,
        student_id=student.id,
        task_instance_id=task.id,
        source_code="def solve():\n    pass\n",
    )
    with pytest.raises(InvalidHintRequest, match="next hint level is 1"):
        record_hint_usage(db_session, task=task, level=2, revision_id=revision.id, now=NOW)
    first = record_hint_usage(db_session, task=task, level=1, revision_id=revision.id, now=NOW)
    second = record_hint_usage(db_session, task=task, level=2, revision_id=revision.id, now=NOW)
    assert (first.sequence, first.hint_key, first.cost, first.content) == (
        1,
        "first",
        10,
        "First hint.",
    )
    assert (second.sequence, second.hint_key, second.cost, second.content) == (
        2,
        "second",
        25,
        "Second hint.",
    )
    with pytest.raises(InvalidHintRequest, match="maximum hint level is 2"):
        record_hint_usage(db_session, task=task, level=3, revision_id=revision.id, now=NOW)


def test_hint_revision_must_belong_to_task(
    db_session: Session, hint_task: tuple[TaskInstance, User]
) -> None:
    task, _student = hint_task
    with pytest.raises(InvalidHintRequest, match="revision does not belong"):
        record_hint_usage(db_session, task=task, level=1, revision_id=uuid4(), now=NOW)
