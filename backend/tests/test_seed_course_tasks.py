"""Tests for ``bootstrap.seed_course_tasks`` (V1.1 fix for problem 9).

Problem: the canonical course carries 93 nodes but only the demo guest's
single node had a ``TaskDefinition`` + ``TaskVersion``. Real students compiling
a path via onboarding received ``today`` items with ``task_version_id=None``
("缺少任务实例"). ``seed_course_tasks`` publishes a basic task for every node
so the learning loop unblocks end-to-end.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bootstrap import seed_course_tasks
from app.contracts.sandbox import SandboxExecutionPolicy, SandboxRunStatus
from app.knowledge_seed import seed_published_course
from app.models import KnowledgeNode, TaskDefinition, TaskVersion
from app.task_policy import parse_task_policy
from sandbox.runner import execute_request


def _node_count(db: Session, course_id: object) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(KnowledgeNode)
            .where(KnowledgeNode.course_id == course_id)
        )
        or 0
    )


def test_seed_course_tasks_creates_definitions_and_versions_for_every_node(
    db_session: Session,
) -> None:
    seed_result = seed_published_course(db_session)
    db_session.flush()

    created = seed_course_tasks(db_session)
    node_count = _node_count(db_session, seed_result.course_id)

    assert node_count == 93
    # First run: every node receives a brand-new definition.
    assert created == node_count

    definitions = list(
        db_session.scalars(
            select(TaskDefinition).where(TaskDefinition.course_id == seed_result.course_id)
        )
    )
    assert len(definitions) == node_count
    # One definition per node (no duplicates from the seed loop).
    node_ids = [d.node_id for d in definitions]
    assert len(set(node_ids)) == node_count

    for definition in definitions:
        versions = list(
            db_session.scalars(
                select(TaskVersion).where(TaskVersion.definition_id == definition.id)
            )
        )
        assert len(versions) >= 1, f"definition {definition.id} has no version"
        assert all(v.published for v in versions)
        # The compiled snapshot must pass the sandbox task-policy guard so
        # students can actually run code against it.
        published = versions[0]
        parse_task_policy(published.snapshot)


def test_seed_course_tasks_is_idempotent(db_session: Session) -> None:
    seed_published_course(db_session)
    db_session.flush()

    first = seed_course_tasks(db_session)
    second = seed_course_tasks(db_session)

    assert first == 93
    # Second run must not duplicate definitions or versions.
    assert second == 0

    definition_count = db_session.scalar(select(func.count()).select_from(TaskDefinition))
    version_count = db_session.scalar(select(func.count()).select_from(TaskVersion))
    assert definition_count == 93
    assert version_count == 93


def test_seed_course_tasks_produces_script_entrypoint(db_session: Session) -> None:
    """Seed tasks use SCRIPT entrypoint so the practice bar is "runs without error".

    A FUNCTION entrypoint would need a per-node function name + argument
    contract that the seed cannot synthesize generically; SCRIPT with a
    ``MATCHES "(?s).*"`` case is the minimum viable practice task. The inline
    ``(?s)`` DOTALL flag is required because ``re.fullmatch(".*", stdout)``
    does not match the trailing ``\\n`` that ``print`` emits.
    """

    seed_published_course(db_session)
    db_session.flush()
    seed_course_tasks(db_session)

    first_version = db_session.scalar(select(TaskVersion))
    assert first_version is not None
    tests_policy = first_version.snapshot["tests_policy"]
    assert tests_policy["entrypoint"]["kind"] == "SCRIPT"
    assert tests_policy["entrypoint"].get("name") is None
    assert tests_policy["visible"][0]["comparison"] == "MATCHES"
    assert tests_policy["visible"][0]["expected_stdout"] == "(?s).*"
    assert tests_policy["hidden"] == []


def _harness_request_for_seed_policy(
    source_code: str, tests_policy: dict[str, object]
) -> dict[str, object]:
    """Build a harness execution request straight from a compiled tests_policy.

    Mirrors what ``app.code_execution._execution_request`` sends to the
    Supervisor, but without the DB/orchestration layer: this proves the seed
    policy is executable end-to-end against the real sandbox harness.
    """

    return {
        "protocol_version": "1",
        "request_id": "req-seed-policy",
        "run_id": "run-seed-policy-0123456789abcdef0123456789ab",
        "trace_id": "trc-seed-policy",
        "source_code": source_code,
        "entrypoint": tests_policy["entrypoint"],
        "cases": list(tests_policy["visible"]),  # type: ignore[arg-type]
        "allowed_imports": list(tests_policy["allowed_imports"]),  # type: ignore[arg-type]
        "phase": "VISIBLE",
        "policy": SandboxExecutionPolicy(
            timeout_ms=5_000,
            memory_mb=128,
            pids_limit=32,
            output_limit_bytes=32_768,
            test_limit=256,
            trace_frame_limit=200,
        ).model_dump(mode="json"),
        "trace_enabled": False,
    }


def test_seed_script_policy_runs_hello_without_error(db_session: Session) -> None:
    """Regression for issue 2: the seed SCRIPT policy must accept ``print('hello')``.

    The visible case uses ``MATCHES "(?s).*"``. Without the inline DOTALL flag,
    ``re.fullmatch(".*", "hello\\n")`` returns ``None`` because ``.`` does not
    match the trailing newline emitted by ``print``, so the run would be FAILED
    even though the student's code is correct. A student writing ``print('hello')``
    in the code lab must get a PASSED run with stdout displayed.
    """

    seed_published_course(db_session)
    db_session.flush()
    seed_course_tasks(db_session)

    first_version = db_session.scalar(select(TaskVersion))
    assert first_version is not None
    tests_policy = first_version.snapshot["tests_policy"]

    result = execute_request(_harness_request_for_seed_policy("print('hello')", tests_policy))
    assert result.status == SandboxRunStatus.PASSED
    assert result.passed is True
    assert result.stdout == "hello\n"
    assert result.tests[0].passed is True
    assert result.platform_error is None


def test_seed_script_policy_matches_empty_output(db_session: Session) -> None:
    """The seed pattern also matches a script that produces no output (``(?s).*``
    matches the empty string), so the bar stays "runs without error"."""

    seed_published_course(db_session)
    db_session.flush()
    seed_course_tasks(db_session)

    first_version = db_session.scalar(select(TaskVersion))
    assert first_version is not None
    tests_policy = first_version.snapshot["tests_policy"]

    # A script that runs cleanly but prints nothing.
    result = execute_request(_harness_request_for_seed_policy("x = 1 + 1", tests_policy))
    assert result.status == SandboxRunStatus.PASSED
    assert result.passed is True


def test_seed_script_policy_fails_on_runtime_error(db_session: Session) -> None:
    """The seed bar is "runs without error": a runtime error must still surface
    as ERROR (not PASSED), so the policy is not vacuous."""

    seed_published_course(db_session)
    db_session.flush()
    seed_course_tasks(db_session)

    first_version = db_session.scalar(select(TaskVersion))
    assert first_version is not None
    tests_policy = first_version.snapshot["tests_policy"]

    result = execute_request(
        _harness_request_for_seed_policy("print('oops')\nraise ValueError('boom')", tests_policy)
    )
    assert result.status == SandboxRunStatus.ERROR
    assert result.passed is False
    assert result.user_error is not None
    assert "ValueError" in result.user_error
