"""Deterministic task snapshot compilation and replay-safe starts (BE-004)."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    TaskDefinition,
    TaskInstance,
    TaskInstanceStatus,
    TaskStatusHistory,
    TaskVersion,
    User,
)


class InvalidTaskCompileInput(ValueError):
    """Compilation input violates the immutable task contract."""


class TaskVersionUnavailable(Exception):
    """The task version does not exist or is not published."""


class TaskScopeError(Exception):
    """The student and task version do not share a tenant."""


@dataclass(frozen=True)
class CompileInput:
    prompt: str
    tests_policy: dict[str, Any]
    hint_policy: dict[str, Any]
    mastery_policy: dict[str, Any]
    resource_versions: dict[str, Any]
    scenario_key: str


def _canonical_snapshot(data: dict[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        encoded = json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise InvalidTaskCompileInput("task snapshot must be JSON serializable") from exc
    canonical: dict[str, Any] = json.loads(encoded)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return canonical, digest


def _compile_snapshot(
    definition: TaskDefinition, compile_input: CompileInput
) -> tuple[dict[str, Any], str]:
    prompt = compile_input.prompt.strip()
    scenario_key = compile_input.scenario_key.strip()
    if not prompt or len(prompt) > 20_000:
        raise InvalidTaskCompileInput("prompt must contain 1..20000 characters")
    if not scenario_key or len(scenario_key) > 128:
        raise InvalidTaskCompileInput("scenario_key must contain 1..128 characters")
    snapshot = {
        "definition_id": str(definition.id),
        "definition_key": definition.key,
        "definition_title": definition.title,
        "definition_version": definition.version,
        "hint_policy": copy.deepcopy(compile_input.hint_policy),
        "mastery_policy": copy.deepcopy(compile_input.mastery_policy),
        "prompt": prompt,
        "resource_versions": copy.deepcopy(compile_input.resource_versions),
        "scenario_key": scenario_key,
        "tests_policy": copy.deepcopy(compile_input.tests_policy),
    }
    return _canonical_snapshot(snapshot)


def _constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def compile_task_version(
    db: Session, definition: TaskDefinition, compile_input: CompileInput
) -> TaskVersion:
    """Publish a deterministic immutable task version.

    Compiling identical inputs for one definition returns the existing version
    by digest; a changed canonical snapshot receives the next version number.
    """

    stored_definition = db.get(TaskDefinition, definition.id)
    if stored_definition is None:
        raise InvalidTaskCompileInput("task definition must be persisted")
    snapshot, digest = _compile_snapshot(stored_definition, compile_input)

    existing = db.scalar(
        select(TaskVersion).where(
            TaskVersion.definition_id == stored_definition.id,
            TaskVersion.snapshot_digest == digest,
        )
    )
    if existing is not None:
        return existing

    latest = db.scalar(
        select(TaskVersion)
        .where(TaskVersion.definition_id == stored_definition.id)
        .order_by(TaskVersion.version.desc())
        .limit(1)
        .with_for_update()
    )
    task_version = TaskVersion(
        tenant_id=stored_definition.tenant_id,
        definition_id=stored_definition.id,
        version=(latest.version if latest is not None else 0) + 1,
        snapshot=snapshot,
        snapshot_digest=digest,
        scenario_key=compile_input.scenario_key.strip(),
        published=True,
        published_at=datetime.now(UTC),
    )
    try:
        with db.begin_nested():
            db.add(task_version)
            db.flush()
    except IntegrityError as exc:
        if _constraint_name(exc) in {"uq_task_version_digest", "uq_task_version_number"}:
            replay = db.scalar(
                select(TaskVersion).where(
                    TaskVersion.definition_id == stored_definition.id,
                    TaskVersion.snapshot_digest == digest,
                )
            )
            if replay is not None:
                return replay
        raise
    return task_version


def start_task_instance(
    db: Session,
    *,
    student_id: UUID,
    task_version_id: UUID,
    active_key: str,
) -> TaskInstance:
    """Start or replay the one active instance for a student/version/key."""

    clean_key = active_key.strip()
    if not clean_key or len(clean_key) > 128:
        raise InvalidTaskCompileInput("active_key must contain 1..128 characters")
    version = db.get(TaskVersion, task_version_id)
    if version is None or not version.published:
        raise TaskVersionUnavailable("published task version not found")
    student = db.scalar(
        select(User).where(
            User.id == student_id,
            User.tenant_id == version.tenant_id,
        )
    )
    if student is None:
        raise TaskScopeError("student and task version are in different tenants")

    existing = db.scalar(
        select(TaskInstance).where(
            TaskInstance.student_id == student_id,
            TaskInstance.task_version_id == task_version_id,
            TaskInstance.active_key == clean_key,
            TaskInstance.status == TaskInstanceStatus.ACTIVE,
        )
    )
    if existing is not None:
        return existing

    instance = TaskInstance(
        tenant_id=version.tenant_id,
        student_id=student_id,
        task_version_id=version.id,
        active_key=clean_key,
        status=TaskInstanceStatus.ACTIVE,
        snapshot=copy.deepcopy(version.snapshot),
        snapshot_digest=version.snapshot_digest,
    )
    try:
        with db.begin_nested():
            db.add(instance)
            db.flush()
            db.add(
                TaskStatusHistory(
                    tenant_id=version.tenant_id,
                    task_instance_id=instance.id,
                    from_status=None,
                    to_status=TaskInstanceStatus.ACTIVE,
                    reason="STARTED",
                )
            )
            db.flush()
    except IntegrityError as exc:
        if _constraint_name(exc) == "uq_task_instance_active":
            replay = db.scalar(
                select(TaskInstance).where(
                    TaskInstance.student_id == student_id,
                    TaskInstance.task_version_id == task_version_id,
                    TaskInstance.active_key == clean_key,
                    TaskInstance.status == TaskInstanceStatus.ACTIVE,
                )
            )
            if replay is not None:
                return replay
        raise
    return instance
