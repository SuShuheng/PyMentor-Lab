"""测试共享 fixture。

BE-002 起身份持久化用真实 PostgreSQL（docker-compose）。为缓解 Windows 上
psycopg 首次握手慢的问题，engine 在 session 级只建一次并复用。每个测试在
savepoint 内运行并回滚，实现隔离而不重复连接。
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

# 测试默认关闭启动时 bootstrap，避免 lifespan 触发真实库连接污染测试隔离。
os.environ.setdefault("PYMENTOR_BOOTSTRAP_ON_STARTUP", "false")

# 测试默认连 docker-compose 的 postgres；可用环境变量覆盖。
TEST_DB_URL = os.environ.get(
    "PYMENTOR_DATABASE_URL",
    "postgresql+psycopg://pymentor:pymentor_dev@localhost:5432/pymentor",
)


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
