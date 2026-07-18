"""BE-004 learning-loop ORM model invariants."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index

from app.models.learning import (
    LearningContext,
    MasteryState,
    MasteryStatus,
    ProfileDimension,
    ProfileDimensionScore,
    ReviewSchedule,
    ReviewStatus,
    TaskInstance,
    TaskInstanceStatus,
)


def _check_names(model: type[object]) -> set[str | None]:
    return {
        constraint.name
        for constraint in model.__table__.constraints  # type: ignore[attr-defined]
        if isinstance(constraint, CheckConstraint)
    }


def test_learning_loop_enums_are_stable() -> None:
    assert [item.value for item in ProfileDimension] == [
        "CONCEPT_KNOWLEDGE",
        "EXECUTION_MODEL",
        "IMPLEMENTATION",
        "DECOMPOSITION",
        "DEBUGGING",
        "TESTING",
        "TRANSFER",
        "INDEPENDENCE_SUPPORT",
    ]
    assert [item.value for item in MasteryStatus] == [
        "UNSEEN",
        "LEARNING",
        "PASSED_WITH_HELP",
        "INITIAL_MASTERY",
        "STABLE_MASTERY",
        "REVIEW_REQUIRED",
    ]
    assert [item.value for item in ReviewStatus] == [
        "SCHEDULED",
        "DUE",
        "COMPLETED",
        "CANCELLED",
    ]
    assert [item.value for item in TaskInstanceStatus] == [
        "ACTIVE",
        "SUBMITTED",
        "COMPLETED",
        "CANCELLED",
    ]


def test_learning_loop_models_register_expected_tables() -> None:
    assert LearningContext.__tablename__ == "learning_contexts"
    assert MasteryState.__tablename__ == "mastery_states"
    assert ReviewSchedule.__tablename__ == "review_schedules"
    assert TaskInstance.__tablename__ == "task_instances"


def test_score_and_context_bounds_are_database_constraints() -> None:
    assert {
        "ck_profile_dimension_score_range",
        "ck_profile_dimension_confidence_range",
        "ck_profile_dimension_support_level_range",
    } <= _check_names(ProfileDimensionScore)
    assert "ck_learning_context_daily_minutes_nonnegative" in _check_names(LearningContext)


def test_active_task_uniqueness_is_a_partial_index() -> None:
    index = next(
        item
        for item in TaskInstance.__table__.indexes
        if isinstance(item, Index) and item.name == "uq_task_instance_active"
    )
    assert index.unique is True
    assert index.dialect_options["postgresql"]["where"] is not None
