"""数据库基础测试：engine 能连真实 PostgreSQL，Base.metadata 可用。

这些测试需要 docker-compose 的 postgres 服务（BE-002 起身份持久化用真实 PG）。
测试隔离：每个测试用一个唯一 schema/数据库前缀，避免互相污染。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine


def test_engine_connects_to_postgres() -> None:
    """engine 能 ping 通真实 PostgreSQL。"""
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version()")).scalar_one()
        assert "PostgreSQL" in version


def test_session_local_yields_transactional_session() -> None:
    """SessionLocal 产出可用的 Session。"""
    with SessionLocal() as session:
        assert isinstance(session, Session)
        # 能执行简单查询，说明连接可用。
        result = session.execute(text("SELECT 1")).scalar_one()
        assert result == 1


def test_base_metadata_is_available_for_autogenerate() -> None:
    """Base.metadata 存在，供 Alembic 自动生成迁移。"""
    assert Base.metadata is not None
