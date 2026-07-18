"""Governed, queryable knowledge catalogue introduced by BE-009."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import Uuid

from app.db import Base


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CourseCatalog(Base):
    __tablename__ = "course_catalog"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    audience: Mapped[str] = mapped_column(String(512), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    content_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    chapter_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    deep_unit_node_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class CourseChapter(Base):
    __tablename__ = "course_chapters"
    __table_args__ = (
        UniqueConstraint("course_id", "sequence", name="uq_course_chapters_sequence"),
        CheckConstraint("sequence >= 1", name="ck_course_chapters_sequence_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    course_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("course_catalog.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    learning_objectives: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    content_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    publisher: Mapped[str] = mapped_column(String(128), nullable=False)
    content_scope: Mapped[str] = mapped_column(String(512), nullable=False)
    content_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class KnowledgeMasteryPolicy(Base):
    __tablename__ = "knowledge_mastery_policies"
    __table_args__ = (
        CheckConstraint(
            "pass_threshold >= 0 AND pass_threshold <= 1",
            name="ck_knowledge_mastery_pass_threshold",
        ),
        CheckConstraint("stable_attempts >= 1", name="ck_knowledge_mastery_stable_attempts"),
        CheckConstraint(
            "max_support_level >= 0 AND max_support_level <= 3",
            name="ck_knowledge_mastery_support_level",
        ),
        CheckConstraint(
            "min_transfer_score >= 0 AND min_transfer_score <= 1",
            name="ck_knowledge_mastery_transfer_score",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    pass_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    stable_attempts: Mapped[int] = mapped_column(nullable=False)
    max_support_level: Mapped[int] = mapped_column(nullable=False)
    min_transfer_score: Mapped[float] = mapped_column(Float, nullable=False)
    review_intervals_days: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    content_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    __table_args__ = (UniqueConstraint("id", "course_id", name="uq_knowledge_nodes_id_course"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    course_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("course_catalog.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chapter_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("course_chapters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    learning_objectives: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    prerequisites: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    misconceptions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    examples: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    diagnostic_items: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    practice_templates: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    mastery_policy_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_mastery_policies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    content_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class KnowledgeErrorPattern(Base):
    __tablename__ = "knowledge_error_patterns"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    node_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    symptom: Mapped[str] = mapped_column(String(1024), nullable=False)
    misconception: Mapped[str] = mapped_column(String(1024), nullable=False)
    diagnosis_prompts: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    remediation: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    content_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class KnowledgeQuestionTemplate(Base):
    __tablename__ = "knowledge_question_templates"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    node_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_template: Mapped[str] = mapped_column(String(2048), nullable=False)
    parameter_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    answer_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    test_case_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    content_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class KnowledgeTestCase(Base):
    __tablename__ = "knowledge_test_cases"
    __table_args__ = (
        CheckConstraint(
            "timeout_ms >= 100 AND timeout_ms <= 10000",
            name="ck_knowledge_test_cases_timeout",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    node_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    input: Mapped[str] = mapped_column(String(4096), nullable=False)
    expected: Mapped[str] = mapped_column(String(4096), nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False)
    timeout_ms: Mapped[int] = mapped_column(nullable=False)
    content_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
