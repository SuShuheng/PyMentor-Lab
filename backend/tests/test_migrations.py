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
EXPECTED_0005_TABLES = {
    "code_revisions",
    "code_runs",
    "code_run_status_history",
    "test_results",
    "hint_usages",
}
EXPECTED_0006_TABLES = {"agent_definitions", "agent_runs", "agent_tool_calls"}
EXPECTED_0007_TABLES = {
    "course_catalog",
    "course_chapters",
    "knowledge_nodes",
    "knowledge_sources",
    "knowledge_error_patterns",
    "knowledge_question_templates",
    "knowledge_test_cases",
    "knowledge_mastery_policies",
}
EXPECTED_0008_TABLES = {
    "resource_jobs",
    "learning_resources",
    "resource_objects",
    "resource_reviews",
}
EXPECTED_0009_TABLES = {"provider_configs"}


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


def test_migration_0005_creates_code_evidence_tables() -> None:
    """0005 creates all normalized code-evidence tables after a full round trip."""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    actual_tables = set(inspect(engine).get_table_names())
    missing = EXPECTED_0005_TABLES - actual_tables
    assert not missing, f"code-evidence tables missing: {missing}"


def test_code_evidence_database_constraints_are_named() -> None:
    """0005 keeps byte, sequence, version, ordinal, level, and cost bounds in PG."""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    inspector = inspect(engine)
    checks = {
        table: {row["name"] for row in inspector.get_check_constraints(table)}
        for table in ["code_revisions", "code_runs", "test_results", "hint_usages"]
    }
    assert {
        "ck_code_revision_sequence_positive",
        "ck_code_revision_source_bytes",
    } <= checks["code_revisions"]
    assert "ck_code_run_version_positive" in checks["code_runs"]
    assert "ck_test_result_ordinal_positive" in checks["test_results"]
    assert {
        "ck_hint_usage_level_range",
        "ck_hint_usage_cost_range",
    } <= checks["hint_usages"]


def test_migration_0006_creates_agent_audit_tables() -> None:
    """0006 creates normalized agent definitions, runs, and tool calls."""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    actual_tables = set(inspect(engine).get_table_names())
    missing = EXPECTED_0006_TABLES - actual_tables
    assert not missing, f"agent-audit tables missing: {missing}"


def test_agent_audit_uniques_and_checks_are_named() -> None:
    """Run/event and per-run tool sequence idempotency are database-enforced."""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    inspector = inspect(engine)
    run_uniques = {row["name"] for row in inspector.get_unique_constraints("agent_runs")}
    tool_uniques = {row["name"] for row in inspector.get_unique_constraints("agent_tool_calls")}
    run_checks = {row["name"] for row in inspector.get_check_constraints("agent_runs")}
    tool_checks = {row["name"] for row in inspector.get_check_constraints("agent_tool_calls")}
    assert {"uq_agent_runs_event_id", "uq_agent_runs_external_run_id"} <= run_uniques
    assert "uq_agent_tool_calls_run_sequence" in tool_uniques
    assert "ck_agent_runs_latest_sequence_nonnegative" in run_checks
    assert "ck_agent_tool_calls_sequence_positive" in tool_checks


def test_migration_0007_creates_governed_knowledge_catalog() -> None:
    """0007 persists every governed BE-009 asset family."""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    actual_tables = set(inspect(engine).get_table_names())
    missing = EXPECTED_0007_TABLES - actual_tables
    assert not missing, f"knowledge-catalog tables missing: {missing}"


def test_learning_loop_uses_governed_course_and_node_foreign_keys() -> None:
    """Formal learning rows cannot point at absent or cross-course catalogue nodes."""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    inspector = inspect(engine)
    foreign_keys = {
        table: {row["name"] for row in inspector.get_foreign_keys(table)}
        for table in (
            "learning_paths",
            "learning_path_steps",
            "task_definitions",
            "assessment_results",
            "mastery_states",
            "review_schedules",
        )
    }
    assert "fk_learning_paths_course_catalog" in foreign_keys["learning_paths"]
    assert "fk_learning_path_steps_knowledge_node" in foreign_keys["learning_path_steps"]
    assert "fk_task_definitions_course_node" in foreign_keys["task_definitions"]
    assert "fk_assessment_results_course_node" in foreign_keys["assessment_results"]
    assert "fk_mastery_states_course_node" in foreign_keys["mastery_states"]
    assert "fk_review_schedules_course_node" in foreign_keys["review_schedules"]


def test_migration_0008_creates_resource_publication_tables() -> None:
    """0008 persists jobs, artifacts, objects, and both review pipelines."""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    actual_tables = set(inspect(engine).get_table_names())
    missing = EXPECTED_0008_TABLES - actual_tables
    assert not missing, f"resource-publication tables missing: {missing}"


def test_resource_publication_uniques_checks_and_catalog_foreign_key() -> None:
    """Idempotency, versions, progress, and course/node binding are DB-enforced."""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    inspector = inspect(engine)
    job_uniques = {row["name"] for row in inspector.get_unique_constraints("resource_jobs")}
    resource_uniques = {
        row["name"] for row in inspector.get_unique_constraints("learning_resources")
    }
    object_uniques = {row["name"] for row in inspector.get_unique_constraints("resource_objects")}
    review_uniques = {row["name"] for row in inspector.get_unique_constraints("resource_reviews")}
    job_checks = {row["name"] for row in inspector.get_check_constraints("resource_jobs")}
    resource_checks = {
        row["name"] for row in inspector.get_check_constraints("learning_resources")
    }
    job_foreign_keys = {row["name"] for row in inspector.get_foreign_keys("resource_jobs")}

    assert "uq_resource_jobs_tenant_idempotency" in job_uniques
    assert "uq_learning_resources_job_type_version" in resource_uniques
    assert "uq_resource_objects_key" in object_uniques
    assert "uq_resource_reviews_resource_gate_version" in review_uniques
    assert "ck_resource_jobs_progress_range" in job_checks
    assert "ck_learning_resources_version_positive" in resource_checks
    assert "fk_resource_jobs_course_node" in job_foreign_keys


def test_migration_0009_creates_encrypted_provider_configs() -> None:
    """0009 persists tenant-scoped Provider metadata and opaque credential bytes."""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    assert actual_tables >= EXPECTED_0009_TABLES
    columns = {column["name"]: column for column in inspector.get_columns("provider_configs")}
    assert columns["api_key_encrypted"]["type"].__class__.__name__ == "BYTEA"
    assert "api_key" not in columns


def test_provider_config_uniques_and_version_check_are_database_enforced() -> None:
    """Only one enabled config per tenant/type and identities cannot duplicate."""
    _skip_if_no_postgres()
    cfg = _make_config()
    command.upgrade(cfg, "head")

    from app.db import engine

    inspector = inspect(engine)
    unique_names = {
        row["name"] for row in inspector.get_unique_constraints("provider_configs")
    }
    indexes = {row["name"]: row for row in inspector.get_indexes("provider_configs")}
    checks = {row["name"] for row in inspector.get_check_constraints("provider_configs")}
    assert "uq_provider_configs_identity" in unique_names
    assert indexes["uq_provider_configs_enabled_type"]["unique"] is True
    assert "ck_provider_configs_version_positive" in checks
