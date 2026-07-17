"""迁移测试：upgrade/downgrade 往返 + 0002 表结构验证。

连真实 PostgreSQL（docker-compose），验证 PG 特有 DDL（Uuid 类型、唯一约束、
外键）。迁移是 DDL，不在 savepoint 内回滚，因此在默认库上直接往返。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "migrations" / "alembic.ini"
DB_URL = os.environ.get(
    "PYMENTOR_DATABASE_URL",
    "postgresql+psycopg://pymentor:pymentor_dev@localhost:5432/pymentor",
)

EXPECTED_0002_TABLES = {"tenants", "users", "roles", "user_roles", "user_sessions"}


def _skip_if_no_postgres() -> None:
    if not DB_URL.startswith("postgres"):
        pytest.skip("PostgreSQL not configured for migration test")


def _make_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent))
    os.environ["PYMENTOR_DATABASE_URL"] = DB_URL
    return cfg


def test_migration_upgrade_downgrade_round_trip() -> None:
    """upgrade head → downgrade base → upgrade head 必须成功（连真实 PG）。"""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_migration_0002_creates_identity_tables() -> None:
    """0002 迁移必须创建身份权限的全部表（设计 §15.1）。"""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    missing = EXPECTED_0002_TABLES - actual_tables
    assert not missing, f"identity tables missing: {missing}"


def test_users_table_has_unique_constraints() -> None:
    """users 表必须有租户级邮箱/学号唯一约束（重复注册防护）。"""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    inspector = inspect(engine)
    uniques = inspector.get_unique_constraints("users")
    constraint_names = {u["name"] for u in uniques}
    assert "uq_users_tenant_email" in constraint_names
    assert "uq_users_tenant_student_no" in constraint_names
