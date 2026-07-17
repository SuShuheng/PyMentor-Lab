"""测试共享 fixture。

BE-002 起身份持久化用真实 PostgreSQL（docker-compose）。为缓解 Windows 上
psycopg 首次握手慢的问题，engine 在 session 级只建一次并复用。每个测试在
savepoint 内运行并回滚，实现隔离而不重复连接。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import (
    IdempotencyKey,
    TaskDefinition,
    TaskInstance,
    TaskInstanceStatus,
    TaskVersion,
    Tenant,
    User,
    UserStatus,
)

# 测试默认关闭启动时 bootstrap，避免 lifespan 触发真实库连接污染测试隔离。
os.environ.setdefault("PYMENTOR_BOOTSTRAP_ON_STARTUP", "false")

# 测试默认连 docker-compose 的 postgres；可用环境变量覆盖。
TEST_DB_URL = os.environ.get(
    "PYMENTOR_DATABASE_URL",
    "postgresql+psycopg://pymentor:pymentor_dev@localhost:5432/pymentor",
)

# BE-005 共享常量与快照（test_code_runs / test_code_execution 共用）。
NOW = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
COURSE_ID = UUID("00000000-0000-0000-0000-000000000501")
NODE_ID = UUID("00000000-0000-0000-0000-000000000502")


@dataclass(slots=True)
class CodeContext:
    tenant: Tenant
    student: User
    task: TaskInstance
    idempotency: IdempotencyKey


def code_snapshot() -> dict[str, object]:
    """BE-005 共享任务快照：visible + hidden + hint policy。"""

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


@pytest.fixture()
def code_context(db_session: Session) -> CodeContext:
    """构造 BE-005 共享的 tenant/student/task/idempotency 上下文。"""

    suffix = uuid4().hex
    tenant = Tenant(slug=f"code-{suffix}", name="Code Evidence")
    db_session.add(tenant)
    db_session.flush()
    student = User(
        tenant_id=tenant.id,
        email=f"code-{suffix}@example.com",
        password_hash="not-used",
        status=UserStatus.ACTIVE,
    )
    db_session.add(student)
    db_session.flush()
    definition = TaskDefinition(
        tenant_id=tenant.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        key=f"sum-{suffix}",
        title="Sum task",
    )
    db_session.add(definition)
    db_session.flush()
    snapshot = code_snapshot()
    version = TaskVersion(
        tenant_id=tenant.id,
        definition_id=definition.id,
        version=1,
        snapshot=snapshot,
        snapshot_digest="a" * 64,
        scenario_key="sum-v1",
        published=True,
        published_at=NOW,
    )
    db_session.add(version)
    db_session.flush()
    task = TaskInstance(
        tenant_id=tenant.id,
        student_id=student.id,
        task_version_id=version.id,
        active_key=f"code-{suffix}",
        status=TaskInstanceStatus.ACTIVE,
        snapshot=snapshot,
        snapshot_digest=version.snapshot_digest,
        version=1,
    )
    idempotency = IdempotencyKey(
        key=f"idem-{suffix}",
        tenant_id=tenant.id,
        user_id=student.id,
        endpoint="POST /api/v1/code/runs",
        expires_at=NOW + timedelta(days=1),
    )
    db_session.add_all([task, idempotency])
    db_session.flush()
    return CodeContext(tenant, student, task, idempotency)


def _has_postgres() -> bool:
    return TEST_DB_URL.startswith("postgres")


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Session 级共享 engine，避免重复 TCP 握手。"""
    if not _has_postgres():
        pytest.skip("PostgreSQL not configured for this test run")
    engine = create_engine(TEST_DB_URL, pool_pre_ping=True, future=True)
    # 探活一次，连不上则跳过（不让整个 session 挂起）。
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine: Engine) -> Iterator[Session]:
    """每个测试一个 Session，运行在事务/savepoint 内并回滚，互相隔离。

    注意：BE-002 的迁移测试直接用 alembic 命令而非此 fixture（DDL 不在
    savepoint 内回滚）；此 fixture 供需要 ORM 写入的业务测试使用。
    """
    connection = db_engine.connect()
    trans = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    # 嵌套 savepoint，业务代码 commit 时只提交到 savepoint，不污染真实库。
    nested = connection.begin_nested()
    try:
        yield session
    finally:
        session.close()
        if nested.is_active:
            nested.rollback()
        if trans.is_active:
            trans.rollback()
        connection.close()
