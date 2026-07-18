"""Strict, versioned course-asset contracts and deterministic validation.

The JSON documents governed by BE-009 are the reviewable source of truth for
the course catalogue.  This module deliberately accepts plain mappings at the
validation boundary so build tooling can return a report instead of terminating
on the first malformed asset.
"""

from __future__ import annotations

import hashlib
import json
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
    required_chapter_count: Annotated[int, Field(ge=1)]
    minimum_node_count: Annotated[int, Field(ge=1)]
    required_deep_unit_count: Annotated[int, Field(ge=1)]
    deep_unit_node_ids: Annotated[list[UUID], Field(min_length=1)]
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
    counts: dict[str, int]
    content_digest: str


ASSET_SCHEMA_MODELS: dict[str, type[StrictAssetModel]] = {
    "course.schema.json": CourseAsset,
    "node.schema.json": NodeAsset,
    "source.schema.json": SourceAsset,
    "error-pattern.schema.json": ErrorPatternAsset,
    "question-template.schema.json": QuestionTemplateAsset,
    "test-case.schema.json": TestCaseAsset,
    "mastery-policy.schema.json": MasteryPolicyAsset,
    "course-bundle.schema.json": CourseAssetBundle,
}


def generate_asset_schemas() -> dict[str, dict[str, Any]]:
    """Return deterministic JSON Schemas for every governed asset contract."""

    schemas: dict[str, dict[str, Any]] = {}
    for filename, model in ASSET_SCHEMA_MODELS.items():
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://pymentor-lab.local/schemas/v1/{filename}"
        schemas[filename] = schema
    return schemas


def _format_error_path(location: tuple[int | str, ...]) -> str:
    parts: list[str] = []
    for segment in location:
        if isinstance(segment, int):
            parts[-1] = f"{parts[-1]}[{segment}]"
        else:
            parts.append(segment)
    return ".".join(parts)


def _prerequisite_cycle_findings(bundle: CourseAssetBundle) -> list[ValidationFinding]:
    node_ids = {node.node_id for node in bundle.nodes}
    adjacency = {
        node.node_id: [
            prerequisite for prerequisite in node.prerequisites if prerequisite in node_ids
        ]
        for node in bundle.nodes
    }
    state: dict[UUID, int] = {}
    stack: list[UUID] = []
    cycles: set[tuple[str, ...]] = set()

    def visit(node_id: UUID) -> None:
        state[node_id] = 1
        stack.append(node_id)
        for prerequisite in adjacency[node_id]:
            if state.get(prerequisite, 0) == 0:
                visit(prerequisite)
            elif state.get(prerequisite) == 1:
                cycle_start = stack.index(prerequisite)
                cycle = tuple(str(item) for item in stack[cycle_start:])
                cycles.add(tuple(sorted(cycle)))
        stack.pop()
        state[node_id] = 2

    for node_id in sorted(node_ids, key=str):
        if state.get(node_id, 0) == 0:
            visit(node_id)

    return [
        ValidationFinding(
            code="PREREQUISITE_CYCLE",
            path="nodes",
            message=f"prerequisite cycle contains: {', '.join(cycle)}",
        )
        for cycle in sorted(cycles)
    ]


def _semantic_findings(bundle: CourseAssetBundle) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    chapter_ids = {chapter.chapter_id for chapter in bundle.chapters}
    node_ids = {node.node_id for node in bundle.nodes}
    source_ids = {source.source_id for source in bundle.sources}
    question_ids = {question.question_id for question in bundle.question_templates}
    test_ids = {test_case.test_id for test_case in bundle.test_cases}
    policy_ids = {policy.policy_id for policy in bundle.mastery_policies}

    identifier_groups: tuple[tuple[str, list[StrictAssetModel], str], ...] = (
        ("chapters", list(bundle.chapters), "chapter_id"),
        ("nodes", list(bundle.nodes), "node_id"),
        ("sources", list(bundle.sources), "source_id"),
        ("error_patterns", list(bundle.error_patterns), "error_id"),
        ("question_templates", list(bundle.question_templates), "question_id"),
        ("test_cases", list(bundle.test_cases), "test_id"),
        ("mastery_policies", list(bundle.mastery_policies), "policy_id"),
    )
    for group_name, assets, identifier_field in identifier_groups:
        seen: set[str] = set()
        for index, asset in enumerate(assets):
            identifier = str(getattr(asset, identifier_field))
            if identifier in seen:
                findings.append(
                    ValidationFinding(
                        code="DUPLICATE_ID",
                        path=f"{group_name}[{index}].{identifier_field}",
                        message=f"duplicate asset identifier: {identifier}",
                    )
                )
            seen.add(identifier)

    def add(code: str, path: str, target: UUID) -> None:
        findings.append(
            ValidationFinding(code=code, path=path, message=f"referenced asset not found: {target}")
        )

    for index, chapter_id in enumerate(bundle.course.chapter_ids):
        if chapter_id not in chapter_ids:
            add("REFERENCE_MISSING", f"course.chapter_ids[{index}]", chapter_id)

    if len(bundle.chapters) != bundle.course.required_chapter_count:
        findings.append(
            ValidationFinding(
                code="CHAPTER_COUNT_INVALID",
                path="chapters",
                message=(
                    f"expected {bundle.course.required_chapter_count} chapters, "
                    f"found {len(bundle.chapters)}"
                ),
            )
        )
    if len(bundle.nodes) < bundle.course.minimum_node_count:
        findings.append(
            ValidationFinding(
                code="NODE_COUNT_INVALID",
                path="nodes",
                message=(
                    f"expected at least {bundle.course.minimum_node_count} nodes, "
                    f"found {len(bundle.nodes)}"
                ),
            )
        )
    if len(bundle.course.deep_unit_node_ids) != bundle.course.required_deep_unit_count:
        findings.append(
            ValidationFinding(
                code="DEEP_UNIT_COUNT_INVALID",
                path="course.deep_unit_node_ids",
                message=(
                    f"expected {bundle.course.required_deep_unit_count} deep units, "
                    f"found {len(bundle.course.deep_unit_node_ids)}"
                ),
            )
        )
    for index, node_id in enumerate(bundle.course.deep_unit_node_ids):
        if node_id not in node_ids:
            add("REFERENCE_MISSING", f"course.deep_unit_node_ids[{index}]", node_id)

    for chapter_index, chapter in enumerate(bundle.chapters):
        if chapter.course_id != bundle.course.course_id:
            add("REFERENCE_MISSING", f"chapters[{chapter_index}].course_id", chapter.course_id)
        for reference_index, node_id in enumerate(chapter.node_ids):
            if node_id not in node_ids:
                add(
                    "REFERENCE_MISSING",
                    f"chapters[{chapter_index}].node_ids[{reference_index}]",
                    node_id,
                )

    for node_index, node in enumerate(bundle.nodes):
        if node.chapter_id not in chapter_ids:
            add("REFERENCE_MISSING", f"nodes[{node_index}].chapter_id", node.chapter_id)
        for reference_index, prerequisite in enumerate(node.prerequisites):
            if prerequisite not in node_ids:
                add(
                    "REFERENCE_MISSING",
                    f"nodes[{node_index}].prerequisites[{reference_index}]",
                    prerequisite,
                )
        for reference_index, source_id in enumerate(node.source_ids):
            if source_id not in source_ids:
                add(
                    "SOURCE_MISSING",
                    f"nodes[{node_index}].source_ids[{reference_index}]",
                    source_id,
                )
        for field_name in ("diagnostic_items", "practice_templates"):
            for reference_index, question_id in enumerate(getattr(node, field_name)):
                if question_id not in question_ids:
                    add(
                        "QUESTION_TEMPLATE_MISSING",
                        f"nodes[{node_index}].{field_name}[{reference_index}]",
                        question_id,
                    )
        if node.mastery_policy_id not in policy_ids:
            add(
                "MASTERY_POLICY_MISSING",
                f"nodes[{node_index}].mastery_policy_id",
                node.mastery_policy_id,
            )

    for error_index, pattern in enumerate(bundle.error_patterns):
        for reference_index, node_id in enumerate(pattern.node_ids):
            if node_id not in node_ids:
                add(
                    "REFERENCE_MISSING",
                    f"error_patterns[{error_index}].node_ids[{reference_index}]",
                    node_id,
                )
        for reference_index, source_id in enumerate(pattern.source_ids):
            if source_id not in source_ids:
                add(
                    "SOURCE_MISSING",
                    f"error_patterns[{error_index}].source_ids[{reference_index}]",
                    source_id,
                )

    covered_by_error_pattern = {
        node_id for pattern in bundle.error_patterns for node_id in pattern.node_ids
    }
    for index, node_id in enumerate(bundle.course.deep_unit_node_ids):
        if node_id in node_ids and node_id not in covered_by_error_pattern:
            findings.append(
                ValidationFinding(
                    code="DEEP_UNIT_ERROR_PATTERN_MISSING",
                    path=f"course.deep_unit_node_ids[{index}]",
                    message=f"deep unit has no linked error pattern: {node_id}",
                )
            )

    official_source_hosts = {
        "Python Software Foundation": "docs.python.org",
        "Python Enhancement Proposals": "peps.python.org",
    }
    for source_index, source in enumerate(bundle.sources):
        expected_host = official_source_hosts[source.publisher]
        if source.url.host != expected_host:
            findings.append(
                ValidationFinding(
                    code="SOURCE_NOT_WHITELISTED",
                    path=f"sources[{source_index}].url",
                    message=(
                        f"publisher {source.publisher} requires official host {expected_host}"
                    ),
                )
            )

    for question_index, question in enumerate(bundle.question_templates):
        if question.node_id not in node_ids:
            add(
                "REFERENCE_MISSING",
                f"question_templates[{question_index}].node_id",
                question.node_id,
            )
        for reference_index, test_id in enumerate(question.test_case_ids):
            if test_id not in test_ids:
                add(
                    "TEST_CASE_MISSING",
                    f"question_templates[{question_index}].test_case_ids[{reference_index}]",
                    test_id,
                )
        for reference_index, source_id in enumerate(question.source_ids):
            if source_id not in source_ids:
                add(
                    "SOURCE_MISSING",
                    f"question_templates[{question_index}].source_ids[{reference_index}]",
                    source_id,
                )

    for test_index, test_case in enumerate(bundle.test_cases):
        if test_case.node_id not in node_ids:
            add("REFERENCE_MISSING", f"test_cases[{test_index}].node_id", test_case.node_id)

    versioned_groups: tuple[tuple[str, list[StrictAssetModel]], ...] = (
        ("chapters", list(bundle.chapters)),
        ("nodes", list(bundle.nodes)),
        ("sources", list(bundle.sources)),
        ("error_patterns", list(bundle.error_patterns)),
        ("question_templates", list(bundle.question_templates)),
        ("test_cases", list(bundle.test_cases)),
        ("mastery_policies", list(bundle.mastery_policies)),
    )
    if bundle.course.version != bundle.content_version:
        findings.append(
            ValidationFinding(
                code="VERSION_CONFLICT",
                path="course.version",
                message=f"expected content version {bundle.content_version}",
            )
        )
    for group_name, assets in versioned_groups:
        for index, asset in enumerate(assets):
            version = str(asset.model_dump()["version"])
            if version != bundle.content_version:
                findings.append(
                    ValidationFinding(
                        code="VERSION_CONFLICT",
                        path=f"{group_name}[{index}].version",
                        message=f"expected content version {bundle.content_version}",
                    )
                )

    findings.extend(_prerequisite_cycle_findings(bundle))
    findings.sort(key=lambda finding: (finding.path, finding.code, finding.message))
    return findings


def validate_course_document(document: Mapping[str, object]) -> CourseValidationReport:
    """Validate one raw course document and return stable, machine-readable findings."""

    serialized = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    content_digest = hashlib.sha256(serialized.encode()).hexdigest()
    try:
        bundle = CourseAssetBundle.model_validate(document)
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
        return CourseValidationReport(
            valid=False,
            findings=findings,
            counts={},
            content_digest=content_digest,
        )

    findings = _semantic_findings(bundle)
    counts = {
        "chapters": len(bundle.chapters),
        "nodes": len(bundle.nodes),
        "sources": len(bundle.sources),
        "error_patterns": len(bundle.error_patterns),
        "question_templates": len(bundle.question_templates),
        "test_cases": len(bundle.test_cases),
        "mastery_policies": len(bundle.mastery_policies),
        "deep_units": len(bundle.course.deep_unit_node_ids),
    }
    return CourseValidationReport(
        valid=not findings,
        findings=findings,
        counts=counts,
        content_digest=content_digest,
    )
