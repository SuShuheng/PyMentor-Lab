"""Immutable task compilation and replay-safe instance start tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import TaskDefinition, TaskStatusHistory, TaskVersion, UserStatus
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant
from app.task_compiler import (
    CompileInput,
    InvalidTaskCompileInput,
    TaskScopeError,
    TaskVersionUnavailable,
    compile_task_version,
    start_task_instance,
)

COURSE_ID = UUID("00000000-0000-0000-0000-000000000201")
NODE_ID = UUID("00000000-0000-0000-0000-000000000202")


@pytest.fixture()
def student_and_definition(db_session: Session):
    tenant = get_or_create_tenant(db_session, slug=f"task-{uuid4().hex}", name="Task Test")
    db_session.flush()
    student = create_student_user(
        db_session,
        tenant_id=tenant.id,
        email=f"task-{uuid4().hex}@test.local",
        password_hash=hash_password("ValidPass1!"),
    )
    student.status = UserStatus.ACTIVE
    definition = TaskDefinition(
        tenant_id=tenant.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        key=f"loop-boundary-{uuid4().hex}",
        title="Loop boundary repair",
    )
    db_session.add(definition)
    db_session.flush()
    return student, definition


def _compile_input(prompt: str = "Fix the loop boundary") -> CompileInput:
    return CompileInput(
        prompt=prompt,
        tests_policy={"hidden": ["upper_bound"]},
        hint_policy={"max_level": 2},
        mastery_policy={"independence_min": 0.7},
        resource_versions={"lesson": "loops@1"},
        scenario_key="range-stop-v1",
    )


def test_started_instance_keeps_original_snapshot(
    db_session: Session, student_and_definition
) -> None:
    student, definition = student_and_definition
    version = compile_task_version(db_session, definition, _compile_input())
    instance = start_task_instance(
        db_session,
        student_id=student.id,
        task_version_id=version.id,
        active_key="today",
    )
    definition.title = "Changed later"
    version.snapshot["prompt"] = "Mutated in memory"
    db_session.flush()
    assert instance.snapshot["prompt"] == "Fix the loop boundary"
    assert instance.snapshot["definition_title"] == "Loop boundary repair"


def test_active_instance_is_replay_safe(db_session: Session, student_and_definition) -> None:
    student, definition = student_and_definition
    version = compile_task_version(db_session, definition, _compile_input())
    first = start_task_instance(
        db_session,
        student_id=student.id,
        task_version_id=version.id,
        active_key="today",
    )
    second = start_task_instance(
        db_session,
        student_id=student.id,
        task_version_id=version.id,
        active_key="today",
    )
    assert second.id == first.id
    history_count = db_session.scalar(
        select(func.count())
        .select_from(TaskStatusHistory)
        .where(TaskStatusHistory.task_instance_id == first.id)
    )
    assert history_count == 1


def test_compilation_is_digest_deterministic(db_session: Session, student_and_definition) -> None:
    _, definition = student_and_definition
    first = compile_task_version(db_session, definition, _compile_input())
    replay = compile_task_version(db_session, definition, _compile_input())
    changed = compile_task_version(
        db_session, definition, _compile_input(prompt="Fix both loop boundaries")
    )
    assert replay.id == first.id
    assert replay.snapshot_digest == first.snapshot_digest
    assert changed.version == 2
    assert changed.snapshot_digest != first.snapshot_digest


def test_unpublished_task_version_cannot_start(db_session: Session, student_and_definition) -> None:
    student, definition = student_and_definition
    version = compile_task_version(db_session, definition, _compile_input())
    version.published = False
    db_session.flush()
    with pytest.raises(TaskVersionUnavailable):
        start_task_instance(
            db_session,
            student_id=student.id,
            task_version_id=version.id,
            active_key="today",
        )


def test_cross_tenant_student_cannot_start_task(
    db_session: Session, student_and_definition
) -> None:
    _, definition = student_and_definition
    version = compile_task_version(db_session, definition, _compile_input())
    other_tenant = get_or_create_tenant(db_session, slug=f"task-other-{uuid4().hex}", name="Other")
    db_session.flush()
    other_student = create_student_user(
        db_session,
        tenant_id=other_tenant.id,
        email=f"other-{uuid4().hex}@test.local",
        password_hash=hash_password("ValidPass1!"),
    )
    db_session.flush()
    with pytest.raises(TaskScopeError):
        start_task_instance(
            db_session,
            student_id=other_student.id,
            task_version_id=version.id,
            active_key="today",
        )


@pytest.mark.parametrize(
    "compile_input",
    [
        _compile_input(prompt=""),
        CompileInput(
            prompt="Valid",
            tests_policy={},
            hint_policy={},
            mastery_policy={},
            resource_versions={},
            scenario_key="",
        ),
    ],
)
def test_invalid_compile_input_is_rejected(
    db_session: Session, student_and_definition, compile_input: CompileInput
) -> None:
    _, definition = student_and_definition
    with pytest.raises(InvalidTaskCompileInput):
        compile_task_version(db_session, definition, compile_input)


def test_compile_persists_canonical_snapshot(db_session: Session, student_and_definition) -> None:
    _, definition = student_and_definition
    version = compile_task_version(db_session, definition, _compile_input())
    stored = db_session.get(TaskVersion, version.id)
    assert stored is not None
    assert list(stored.snapshot) == sorted(stored.snapshot)
    assert len(stored.snapshot_digest) == 64
