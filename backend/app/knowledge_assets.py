"""Strict, versioned course-asset contracts and deterministic validation.

The JSON documents governed by BE-009 are the reviewable source of truth for
the course catalogue.  This module deliberately accepts plain mappings at the
validation boundary so build tooling can return a report instead of terminating
on the first malformed asset.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

SemanticVersion = Annotated[str, Field(pattern=r"^[1-9]\d*\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")]
NonEmptyText = Annotated[str, Field(min_length=1)]


class StrictAssetModel(BaseModel):
    """Base contract that rejects undeclared asset fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CourseAsset(StrictAssetModel):
    course_id: UUID
    slug: Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
    title: NonEmptyText
    audience: NonEmptyText
    language: Literal["zh-CN"]
    chapter_ids: list[UUID]
    version: SemanticVersion


class ChapterAsset(StrictAssetModel):
    chapter_id: UUID
    course_id: UUID
    order: Annotated[int, Field(ge=1)]
    title: NonEmptyText
    learning_objectives: Annotated[list[NonEmptyText], Field(min_length=1)]
    node_ids: Annotated[list[UUID], Field(min_length=1)]
    version: SemanticVersion


class NodeAsset(StrictAssetModel):
    node_id: UUID
    title: NonEmptyText
    chapter_id: UUID
    learning_objectives: Annotated[list[NonEmptyText], Field(min_length=1)]
    prerequisites: list[UUID]
    misconceptions: Annotated[list[NonEmptyText], Field(min_length=1)]
    examples: Annotated[list[NonEmptyText], Field(min_length=1)]
    diagnostic_items: Annotated[list[UUID], Field(min_length=1)]
    practice_templates: Annotated[list[UUID], Field(min_length=1)]
    mastery_policy_id: UUID
    source_ids: Annotated[list[UUID], Field(min_length=1)]
    version: SemanticVersion


class SourceAsset(StrictAssetModel):
    source_id: UUID
    title: NonEmptyText
    url: HttpUrl
    publisher: Literal["Python Software Foundation", "Python Enhancement Proposals"]
    content_scope: NonEmptyText
    version: SemanticVersion


class ErrorPatternAsset(StrictAssetModel):
    error_id: UUID
    node_ids: Annotated[list[UUID], Field(min_length=1)]
    title: NonEmptyText
    symptom: NonEmptyText
    misconception: NonEmptyText
    diagnosis_prompts: Annotated[list[NonEmptyText], Field(min_length=1)]
    remediation: Annotated[list[NonEmptyText], Field(min_length=1)]
    source_ids: Annotated[list[UUID], Field(min_length=1)]
    version: SemanticVersion


class QuestionTemplateAsset(StrictAssetModel):
    question_id: UUID
    node_id: UUID
    kind: Literal["MULTIPLE_CHOICE", "CODE_COMPLETION", "CODE_REPAIR", "CODE_WRITING"]
    prompt_template: NonEmptyText
    parameter_schema: dict[str, Any]
    answer_schema: dict[str, Any]
    test_case_ids: Annotated[list[UUID], Field(min_length=1)]
    source_ids: Annotated[list[UUID], Field(min_length=1)]
    version: SemanticVersion


class TestCaseAsset(StrictAssetModel):
    test_id: UUID
    node_id: UUID
    kind: Literal["STDOUT", "RETURN_VALUE", "EXCEPTION", "PROPERTY"]
    input: str
    expected: NonEmptyText
    hidden: bool
    timeout_ms: Annotated[int, Field(ge=100, le=10_000)]
    version: SemanticVersion


class MasteryPolicyAsset(StrictAssetModel):
    policy_id: UUID
    name: NonEmptyText
    pass_threshold: Annotated[float, Field(ge=0, le=1)]
    stable_attempts: Annotated[int, Field(ge=1)]
    max_support_level: Annotated[int, Field(ge=0, le=3)]
    min_transfer_score: Annotated[float, Field(ge=0, le=1)]
    review_intervals_days: Annotated[list[Annotated[int, Field(ge=1)]], Field(min_length=1)]
    version: SemanticVersion


class CourseAssetBundle(StrictAssetModel):
    schema_version: SemanticVersion
    content_version: SemanticVersion
    course: CourseAsset
    chapters: list[ChapterAsset]
    nodes: list[NodeAsset]
    sources: list[SourceAsset]
    error_patterns: list[ErrorPatternAsset]
    question_templates: list[QuestionTemplateAsset]
    test_cases: list[TestCaseAsset]
    mastery_policies: list[MasteryPolicyAsset]


class ValidationFinding(StrictAssetModel):
    code: str
    path: str
    message: str


class CourseValidationReport(StrictAssetModel):
    valid: bool
    findings: list[ValidationFinding]


def _format_error_path(location: tuple[int | str, ...]) -> str:
    parts: list[str] = []
    for segment in location:
        if isinstance(segment, int):
            parts[-1] = f"{parts[-1]}[{segment}]"
        else:
            parts.append(segment)
    return ".".join(parts)


def validate_course_document(document: Mapping[str, object]) -> CourseValidationReport:
    """Validate one raw course document and return stable, machine-readable findings."""

    try:
        CourseAssetBundle.model_validate(document)
    except ValidationError as error:
        findings = [
            ValidationFinding(
                code="SCHEMA_REQUIRED" if item["type"] == "missing" else "SCHEMA_INVALID",
                path=_format_error_path(item["loc"]),
                message=item["msg"],
            )
            for item in error.errors(include_url=False)
        ]
        findings.sort(key=lambda finding: (finding.path, finding.code, finding.message))
        return CourseValidationReport(valid=False, findings=findings)

    return CourseValidationReport(valid=True, findings=[])

