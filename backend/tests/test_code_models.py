"""BE-005 code revision, run, result, and hint persistence invariants."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from app.contracts.sandbox import CodeRunMode, CodeRunStatus
from app.models.code import (
    CodeRevision,
    CodeRun,
    CodeRunStatusHistory,
    HintSource,
    HintUsage,
)
from app.models.code import (
    TestResult as CodeTestResult,
)


def _check_names(model: type[object]) -> set[str | None]:
    return {
        constraint.name
        for constraint in model.__table__.constraints  # type: ignore[attr-defined]
        if isinstance(constraint, CheckConstraint)
    }


def _unique_names(model: type[object]) -> set[str | None]:
    return {
        constraint.name
        for constraint in model.__table__.constraints  # type: ignore[attr-defined]
        if isinstance(constraint, UniqueConstraint)
    }


def test_code_evidence_enums_are_stable() -> None:
    assert [item.value for item in CodeRunMode] == ["RUN", "TRACE", "SUBMIT"]
    assert [item.value for item in CodeRunStatus] == [
        "QUEUED",
        "RUNNING",
        "COMPLETED",
        "USER_ERROR",
        "PLATFORM_ERROR",
        "TIMEOUT",
        "CANCELLED",
    ]
    assert [item.value for item in HintSource] == ["STATIC", "AGENT_PROPOSAL"]


def test_code_evidence_models_register_expected_tables() -> None:
    assert {
        CodeRevision.__tablename__,
        CodeRun.__tablename__,
        CodeRunStatusHistory.__tablename__,
        CodeTestResult.__tablename__,
        HintUsage.__tablename__,
    } == {
        "code_revisions",
        "code_runs",
        "code_run_status_history",
        "test_results",
        "hint_usages",
    }


def test_code_run_active_uniqueness_is_partial() -> None:
    index = next(
        item
        for item in CodeRun.__table__.indexes
        if isinstance(item, Index) and item.name == "uq_code_run_active_task"
    )
    assert index.unique is True
    assert index.dialect_options["postgresql"]["where"] is not None


def test_code_evidence_named_checks_cover_all_bounds() -> None:
    assert {
        "ck_code_revision_sequence_positive",
        "ck_code_revision_source_bytes",
    } <= _check_names(CodeRevision)
    assert "ck_code_run_version_positive" in _check_names(CodeRun)
    assert {
        "ck_test_result_ordinal_positive",
        "ck_test_result_duration_nonnegative",
        "ck_test_result_stdout_bytes",
        "ck_test_result_stderr_bytes",
    } <= _check_names(CodeTestResult)
    assert {
        "ck_hint_usage_sequence_positive",
        "ck_hint_usage_level_range",
        "ck_hint_usage_cost_range",
    } <= _check_names(HintUsage)


def test_code_evidence_uniqueness_prevents_duplicate_history_positions() -> None:
    assert {
        "uq_code_revision_sequence",
        "uq_code_revision_digest",
    } <= _unique_names(CodeRevision)
    assert "uq_code_runs_run_id" in _unique_names(CodeRun)
    assert {
        "uq_test_result_ordinal",
        "uq_test_result_case",
    } <= _unique_names(CodeTestResult)
    assert "uq_hint_usage_sequence" in _unique_names(HintUsage)


def test_every_code_evidence_table_has_a_tenant_foreign_key() -> None:
    for model in [
        CodeRevision,
        CodeRun,
        CodeRunStatusHistory,
        CodeTestResult,
        HintUsage,
    ]:
        tenant_column = model.__table__.c.tenant_id
        assert {foreign_key.target_fullname for foreign_key in tenant_column.foreign_keys} == {
            "tenants.id"
        }
