"""Idempotent PostgreSQL seed tests for the governed BE-009 catalogue."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.knowledge_seed import seed_published_course
from app.models import (
    CourseCatalog,
    CourseChapter,
    KnowledgeErrorPattern,
    KnowledgeMasteryPolicy,
    KnowledgeNode,
    KnowledgeQuestionTemplate,
    KnowledgeSource,
    KnowledgeTestCase,
)


def _count(session: Session, model: type[object]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_published_course_seed_is_idempotent(db_session: Session) -> None:
    first = seed_published_course(db_session)
    second = seed_published_course(db_session)

    assert first == second
    assert first.counts == {
        "chapters": 14,
        "nodes": 84,
        "sources": 16,
        "error_patterns": 84,
        "question_templates": 168,
        "test_cases": 168,
        "mastery_policies": 2,
        "deep_units": 4,
    }
    assert _count(db_session, CourseCatalog) == 1
    assert _count(db_session, CourseChapter) == 14
    assert _count(db_session, KnowledgeNode) == 84
    assert _count(db_session, KnowledgeSource) == 16
    assert _count(db_session, KnowledgeErrorPattern) == 84
    assert _count(db_session, KnowledgeQuestionTemplate) == 168
    assert _count(db_session, KnowledgeTestCase) == 168
    assert _count(db_session, KnowledgeMasteryPolicy) == 2
