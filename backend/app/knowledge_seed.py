"""Validated, transactional, idempotent loading of published course assets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Table, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import FromClause

from app.knowledge_assets import CourseAssetBundle, validate_course_document
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

DEFAULT_COURSE_ASSET = (
    Path(__file__).resolve().parents[2]
    / "knowledge"
    / "python-general"
    / "v1"
    / "course-bundle.json"
)


class KnowledgeSeedError(ValueError):
    """The requested asset cannot be accepted as formal catalogue state."""


@dataclass(frozen=True, slots=True)
class KnowledgeSeedResult:
    course_id: UUID
    content_version: str
    content_digest: str
    counts: dict[str, int]


def _uuid_strings(values: list[UUID]) -> list[str]:
    return [str(value) for value in values]


def _upsert(
    session: Session,
    table: FromClause,
    rows: list[dict[str, Any]],
    update_columns: tuple[str, ...],
) -> None:
    if not rows:
        return
    statement = insert(cast(Table, table)).values(rows)
    updates = {column: getattr(statement.excluded, column) for column in update_columns}
    if "updated_at" in table.c:
        updates["updated_at"] = func.now()
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[table.c.id],
            set_=updates,
        )
    )


def load_published_course(path: Path = DEFAULT_COURSE_ASSET) -> tuple[CourseAssetBundle, str]:
    """Load and validate one canonical JSON bundle before any database writes."""

    document = json.loads(path.read_text(encoding="utf-8"))
    report = validate_course_document(document)
    if not report.valid:
        findings = ", ".join(f"{item.code}:{item.path}" for item in report.findings)
        raise KnowledgeSeedError(f"invalid course asset: {findings}")
    return CourseAssetBundle.model_validate(document), report.content_digest


def seed_published_course(
    session: Session, path: Path = DEFAULT_COURSE_ASSET
) -> KnowledgeSeedResult:
    """Upsert the complete bundle in dependency order without committing the transaction."""

    bundle, content_digest = load_published_course(path)
    course = bundle.course

    source_rows = [
        {
            "id": source.source_id,
            "title": source.title,
            "url": str(source.url),
            "publisher": source.publisher,
            "content_scope": source.content_scope,
            "content_version": source.version,
        }
        for source in bundle.sources
    ]
    _upsert(
        session,
        KnowledgeSource.__table__,
        source_rows,
        ("title", "url", "publisher", "content_scope", "content_version"),
    )

    policy_rows = [
        {
            "id": policy.policy_id,
            "name": policy.name,
            "pass_threshold": policy.pass_threshold,
            "stable_attempts": policy.stable_attempts,
            "max_support_level": policy.max_support_level,
            "min_transfer_score": policy.min_transfer_score,
            "review_intervals_days": policy.review_intervals_days,
            "content_version": policy.version,
        }
        for policy in bundle.mastery_policies
    ]
    _upsert(
        session,
        KnowledgeMasteryPolicy.__table__,
        policy_rows,
        (
            "name",
            "pass_threshold",
            "stable_attempts",
            "max_support_level",
            "min_transfer_score",
            "review_intervals_days",
            "content_version",
        ),
    )

    course_rows = [
        {
            "id": course.course_id,
            "slug": course.slug,
            "title": course.title,
            "audience": course.audience,
            "language": course.language,
            "schema_version": bundle.schema_version,
            "content_version": bundle.content_version,
            "source_digest": content_digest,
            "chapter_ids": _uuid_strings(course.chapter_ids),
            "deep_unit_node_ids": _uuid_strings(course.deep_unit_node_ids),
            "published": True,
        }
    ]
    _upsert(
        session,
        CourseCatalog.__table__,
        course_rows,
        (
            "slug",
            "title",
            "audience",
            "language",
            "schema_version",
            "content_version",
            "source_digest",
            "chapter_ids",
            "deep_unit_node_ids",
            "published",
        ),
    )

    chapter_rows = [
        {
            "id": chapter.chapter_id,
            "course_id": chapter.course_id,
            "sequence": chapter.order,
            "title": chapter.title,
            "learning_objectives": chapter.learning_objectives,
            "content_version": chapter.version,
        }
        for chapter in bundle.chapters
    ]
    _upsert(
        session,
        CourseChapter.__table__,
        chapter_rows,
        ("course_id", "sequence", "title", "learning_objectives", "content_version"),
    )

    node_rows = [
        {
            "id": node.node_id,
            "course_id": course.course_id,
            "chapter_id": node.chapter_id,
            "title": node.title,
            "learning_objectives": node.learning_objectives,
            "prerequisites": _uuid_strings(node.prerequisites),
            "misconceptions": node.misconceptions,
            "examples": node.examples,
            "diagnostic_items": _uuid_strings(node.diagnostic_items),
            "practice_templates": _uuid_strings(node.practice_templates),
            "mastery_policy_id": node.mastery_policy_id,
            "source_ids": _uuid_strings(node.source_ids),
            "content_version": node.version,
        }
        for node in bundle.nodes
    ]
    _upsert(
        session,
        KnowledgeNode.__table__,
        node_rows,
        (
            "course_id",
            "chapter_id",
            "title",
            "learning_objectives",
            "prerequisites",
            "misconceptions",
            "examples",
            "diagnostic_items",
            "practice_templates",
            "mastery_policy_id",
            "source_ids",
            "content_version",
        ),
    )

    error_rows = [
        {
            "id": pattern.error_id,
            "title": pattern.title,
            "node_ids": _uuid_strings(pattern.node_ids),
            "symptom": pattern.symptom,
            "misconception": pattern.misconception,
            "diagnosis_prompts": pattern.diagnosis_prompts,
            "remediation": pattern.remediation,
            "source_ids": _uuid_strings(pattern.source_ids),
            "content_version": pattern.version,
        }
        for pattern in bundle.error_patterns
    ]
    _upsert(
        session,
        KnowledgeErrorPattern.__table__,
        error_rows,
        (
            "title",
            "node_ids",
            "symptom",
            "misconception",
            "diagnosis_prompts",
            "remediation",
            "source_ids",
            "content_version",
        ),
    )

    test_rows = [
        {
            "id": test_case.test_id,
            "node_id": test_case.node_id,
            "kind": test_case.kind,
            "input": test_case.input,
            "expected": test_case.expected,
            "hidden": test_case.hidden,
            "timeout_ms": test_case.timeout_ms,
            "content_version": test_case.version,
        }
        for test_case in bundle.test_cases
    ]
    _upsert(
        session,
        KnowledgeTestCase.__table__,
        test_rows,
        (
            "node_id",
            "kind",
            "input",
            "expected",
            "hidden",
            "timeout_ms",
            "content_version",
        ),
    )

    question_rows = [
        {
            "id": question.question_id,
            "node_id": question.node_id,
            "kind": question.kind,
            "prompt_template": question.prompt_template,
            "parameter_schema": question.parameter_schema,
            "answer_schema": question.answer_schema,
            "test_case_ids": _uuid_strings(question.test_case_ids),
            "source_ids": _uuid_strings(question.source_ids),
            "content_version": question.version,
        }
        for question in bundle.question_templates
    ]
    _upsert(
        session,
        KnowledgeQuestionTemplate.__table__,
        question_rows,
        (
            "node_id",
            "kind",
            "prompt_template",
            "parameter_schema",
            "answer_schema",
            "test_case_ids",
            "source_ids",
            "content_version",
        ),
    )
    session.flush()

    counts = {
        "chapters": len(bundle.chapters),
        "nodes": len(bundle.nodes),
        "sources": len(bundle.sources),
        "error_patterns": len(bundle.error_patterns),
        "question_templates": len(bundle.question_templates),
        "test_cases": len(bundle.test_cases),
        "mastery_policies": len(bundle.mastery_policies),
        "deep_units": len(course.deep_unit_node_ids),
    }
    return KnowledgeSeedResult(
        course_id=course.course_id,
        content_version=bundle.content_version,
        content_digest=content_digest,
        counts=counts,
    )
