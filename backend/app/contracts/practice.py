"""Wire contracts for the student self-test (practice) loop (BE-023).

The practice loop is read-only on question templates and records a single
self-test evidence event per attempt. Self-test evidence feeds the
deterministic engine's input stream but DOES NOT auto-advance mastery
(see ``app.api.practice`` for the contract guarantee).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PracticeQuestionKind(StrEnum):
    """Subset of question-template kinds surfaced to students for self-test."""

    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    CODE_COMPLETION = "CODE_COMPLETION"
    CODE_REPAIR = "CODE_REPAIR"
    CODE_WRITING = "CODE_WRITING"


class PracticeQuestionView(BaseModel):
    """A single question template projected for student display.

    The correct answer (``answer_schema.const``) is intentionally NOT exposed
    here so the GET endpoint cannot leak the key before the attempt is scored.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    kind: PracticeQuestionKind
    prompt_template: str = Field(min_length=1)
    parameter_schema: dict[str, Any] = Field(default_factory=dict)


class PracticeQuestionSet(BaseModel):
    """The set of templates attached to a node."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    questions: list[PracticeQuestionView]


class PracticeAnswerItem(BaseModel):
    """One student answer in a self-test attempt."""

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1)
    selected_answer: str = Field(min_length=1, max_length=4096)


class PracticeAttemptRequest(BaseModel):
    """Body of ``POST /api/v1/practice/attempt``."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    answers: list[PracticeAnswerItem] = Field(min_length=1)


class PracticePerQuestionResult(BaseModel):
    """Per-question feedback in an attempt response.

    ``explanation`` may be null when the template carries none; the key is
    always present so clients can render feedback uniformly.
    """

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1)
    correct: bool
    selected_answer: str = Field(min_length=1)
    correct_answer: str = Field(min_length=1)
    explanation: str | None = None


class PracticeAttemptResponse(BaseModel):
    """Scored self-test attempt plus the recorded evidence identifier.

    ``score`` is the fraction of correct answers in ``[0.0, 1.0]``.
    ``evidence_id`` is the ``EvidenceEvent.event_id`` of the recorded self-test
    evidence; the deterministic engine consumes it later without this API
    touching mastery state.
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    correct_count: int = Field(ge=0)
    total_count: int = Field(ge=1)
    per_question: list[PracticePerQuestionResult]
    evidence_id: str = Field(min_length=1, max_length=128)
