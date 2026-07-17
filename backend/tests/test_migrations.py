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
EXPECTED_0003_TABLES = {"evidence_events", "audit_events", "outbox_events", "idempotency_keys"}
EXPECTED_0004_TABLES = {
    "assessment_results",
    "learning_contexts",
    "learning_paths",
    "learning_path_steps",
    "mastery_state_history",
    "mastery_states",
    "profile_change_proposals",
    "profile_dimension_scores",
    "profile_disputes",
    "profile_versions",
    "review_attempts",
    "review_schedules",
    "task_definitions",
    "task_instances",
    "task_status_history",
    "task_versions",
}


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


def test_migration_0003_creates_consistency_tables() -> None:
    """0003 迁移必须创建一致性基础设施的全部表（设计 §15.1 第 8 组）。"""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    missing = EXPECTED_0003_TABLES - actual_tables
    assert not missing, f"consistency tables missing: {missing}"


def test_consistency_tables_have_unique_constraints() -> None:
    """evidence/outbox/idempotency 表必须有 event_id/key 唯一约束（幂等与去重）。"""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    inspector = inspect(engine)

    ev_uniques = {u["name"] for u in inspector.get_unique_constraints("evidence_events")}
    assert "uq_evidence_event_id" in ev_uniques

    ob_uniques = {u["name"] for u in inspector.get_unique_constraints("outbox_events")}
    assert "uq_outbox_event_id" in ob_uniques

    ik_uniques = {u["name"] for u in inspector.get_unique_constraints("idempotency_keys")}
    assert "uq_idempotency_keys_key" in ik_uniques


def test_evidence_table_has_query_indexes_and_confidence_check() -> None:
    """证据多维查询索引与置信度范围必须落到数据库约束。"""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    inspector = inspect(engine)
    index_names = {item["name"] for item in inspector.get_indexes("evidence_events")}
    assert {
        "ix_evidence_events_course_id",
        "ix_evidence_events_node_id",
        "ix_evidence_events_task_id",
    } <= index_names

    check_names = {item["name"] for item in inspector.get_check_constraints("evidence_events")}
    assert "ck_evidence_confidence_range" in check_names


def test_migration_0004_creates_learning_loop_tables() -> None:
    """0004 必须创建确定性学习闭环的全部规范化表。"""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    actual_tables = set(inspect(engine).get_table_names())
    missing = EXPECTED_0004_TABLES - actual_tables
    assert not missing, f"learning-loop tables missing: {missing}"


def test_learning_loop_unique_constraints() -> None:
    """画像版本和学生节点掌握状态必须由数据库防止重复。"""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    inspector = inspect(engine)
    profile_uniques = {row["name"] for row in inspector.get_unique_constraints("profile_versions")}
    mastery_uniques = {row["name"] for row in inspector.get_unique_constraints("mastery_states")}
    assert "uq_profile_student_version" in profile_uniques
    assert "uq_mastery_student_course_node" in mastery_uniques
