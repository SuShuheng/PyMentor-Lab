"""Cross-process BE-006 acceptance assertions against PostgreSQL authority."""

from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AgentRun,
    AgentToolCall,
    AssessmentResult,
    LearningContext,
    LearningPath,
    MasteryState,
    ProfileVersion,
    ReviewSchedule,
    TaskInstance,
)

EVENT_PREFIX = os.environ.get("PYMENTOR_ACCEPTANCE_EVENT_PREFIX")
STUDENT_ID = os.environ.get("PYMENTOR_ACCEPTANCE_STUDENT_ID")


@pytest.mark.skipif(
    EVENT_PREFIX is None or STUDENT_ID is None,
    reason="BE-006 cross-process acceptance identity is not configured",
)
def test_worker_events_are_redacted_and_do_not_mutate_formal_learning_state(
    db_session: Session,
) -> None:
    prefix = f"{EVENT_PREFIX}-%"
    student_id = UUID(STUDENT_ID or "")
    runs = list(
        db_session.scalars(
            select(AgentRun).where(AgentRun.event_id.like(prefix)).order_by(AgentRun.event_id)
        )
    )

    assert len(runs) == 9
    forbidden = next(run for run in runs if run.event_id == f"{EVENT_PREFIX}-forbidden")
    assert forbidden.status == "FAILED_FINAL"
    assert all(run.status == "SUCCEEDED" for run in runs if run is not forbidden)
    assert {run.route for run in runs} == {
        "profile",
        "path",
        "resource",
        "coach",
        "assessment",
    }
    assert all(run.fallback_used for run in runs if run is not forbidden)
    assert all("raw_prompt" not in run.safe_input_snapshot for run in runs)
    assert all("provider_key" not in run.safe_output_snapshot for run in runs)
    replay = next(run for run in runs if run.event_id == f"{EVENT_PREFIX}-replay")
    assert replay.latest_checkpoint_id is not None
    assert replay.checkpoint_thread_id == replay.external_run_id
    tool_calls = list(
        db_session.scalars(
            select(AgentToolCall)
            .join(AgentRun, AgentToolCall.agent_run_id == AgentRun.id)
            .where(AgentRun.event_id.like(prefix))
        )
    )
    assert len(tool_calls) == 1
    assert tool_calls[0].tool_name == "formal_state.write"
    assert tool_calls[0].error_code == "FORBIDDEN_TOOL"

    assert (
        db_session.scalar(
            select(func.count())
            .select_from(LearningContext)
            .where(LearningContext.student_id == student_id)
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ProfileVersion)
            .where(ProfileVersion.student_id == student_id)
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(LearningPath)
            .where(LearningPath.student_id == student_id)
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(TaskInstance)
            .where(TaskInstance.student_id == student_id)
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AssessmentResult)
            .where(AssessmentResult.student_id == student_id)
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(MasteryState)
            .where(MasteryState.student_id == student_id)
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ReviewSchedule)
            .where(ReviewSchedule.student_id == student_id)
        )
        == 0
    )
