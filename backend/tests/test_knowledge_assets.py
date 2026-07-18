"""Versioned knowledge-asset contract and validation tests for BE-009."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.knowledge_assets import generate_asset_schemas, validate_course_document

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PUBLISHED_CATALOG = (
    REPOSITORY_ROOT / "knowledge" / "python-general" / "v1" / "course-bundle.json"
)
PUBLISHED_REPORT = (
    REPOSITORY_ROOT / "knowledge" / "python-general" / "v1" / "validation-report.json"
)


def _minimal_document() -> dict[str, Any]:
    """Return the smallest structurally valid document for focused validator tests."""

    return {
        "schema_version": "1.0.0",
        "content_version": "1.0.0",
        "course": {
            "course_id": "10000000-0000-4000-8000-000000000001",
            "slug": "university-python-general",
            "title": "高校通识 Python",
            "audience": "零基础或基础薄弱的高校非计算机与计算机专业学生",
            "language": "zh-CN",
            "chapter_ids": ["20000000-0000-4000-8000-000000000001"],
            "required_chapter_count": 1,
            "minimum_node_count": 1,
            "required_deep_unit_count": 1,
            "deep_unit_node_ids": ["30000000-0000-4000-8000-000000000001"],
            "version": "1.0.0",
        },
        "chapters": [
            {
                "chapter_id": "20000000-0000-4000-8000-000000000001",
                "course_id": "10000000-0000-4000-8000-000000000001",
                "order": 1,
                "title": "Python 起步",
                "learning_objectives": ["能够运行并解释一个最小 Python 程序"],
                "node_ids": ["30000000-0000-4000-8000-000000000001"],
                "version": "1.0.0",
            }
        ],
        "nodes": [
            {
                "node_id": "30000000-0000-4000-8000-000000000001",
                "title": "运行第一个程序",
                "chapter_id": "20000000-0000-4000-8000-000000000001",
                "learning_objectives": ["区分源代码、解释器与程序输出"],
                "prerequisites": [],
                "misconceptions": ["Python 源文件会被浏览器直接执行"],
                "examples": ["print('你好，Python')"],
                "diagnostic_items": ["60000000-0000-4000-8000-000000000001"],
                "practice_templates": ["60000000-0000-4000-8000-000000000001"],
                "mastery_policy_id": "80000000-0000-4000-8000-000000000001",
                "source_ids": ["40000000-0000-4000-8000-000000000001"],
                "version": "1.0.0",
            }
        ],
        "sources": [
            {
                "source_id": "40000000-0000-4000-8000-000000000001",
                "title": "Python 教程：使用 Python 解释器",
                "url": "https://docs.python.org/zh-cn/3/tutorial/interpreter.html",
                "publisher": "Python Software Foundation",
                "content_scope": "解释器启动、源文件和交互模式",
                "version": "1.0.0",
            }
        ],
        "error_patterns": [
            {
                "error_id": "50000000-0000-4000-8000-000000000001",
                "node_ids": ["30000000-0000-4000-8000-000000000001"],
                "title": "混淆源代码与执行结果",
                "symptom": "把输出文本直接写在源文件中并期待它自动显示",
                "misconception": "源代码本身就是运行结果",
                "diagnosis_prompts": ["哪一部分由解释器执行？"],
                "remediation": ["用 print 调用显式产生标准输出"],
                "source_ids": ["40000000-0000-4000-8000-000000000001"],
                "version": "1.0.0",
            }
        ],
        "question_templates": [
            {
                "question_id": "60000000-0000-4000-8000-000000000001",
                "node_id": "30000000-0000-4000-8000-000000000001",
                "kind": "CODE_COMPLETION",
                "prompt_template": "补全程序，使其输出“你好，Python”。",
                "parameter_schema": {},
                "answer_schema": {"type": "string"},
                "test_case_ids": ["70000000-0000-4000-8000-000000000001"],
                "source_ids": ["40000000-0000-4000-8000-000000000001"],
                "version": "1.0.0",
            }
        ],
        "test_cases": [
            {
                "test_id": "70000000-0000-4000-8000-000000000001",
                "node_id": "30000000-0000-4000-8000-000000000001",
                "kind": "STDOUT",
                "input": "",
                "expected": "你好，Python\n",
                "hidden": False,
                "timeout_ms": 1000,
                "version": "1.0.0",
            }
        ],
        "mastery_policies": [
            {
                "policy_id": "80000000-0000-4000-8000-000000000001",
                "name": "通识课程基础掌握策略",
                "pass_threshold": 0.8,
                "stable_attempts": 2,
                "max_support_level": 1,
                "min_transfer_score": 0.6,
                "review_intervals_days": [1, 3, 7],
                "version": "1.0.0",
            }
        ],
    }


def test_validator_reports_missing_required_field_with_stable_path() -> None:
    document = deepcopy(_minimal_document())
    del document["course"]["title"]

    report = validate_course_document(document)

    assert report.valid is False
    assert [(finding.code, finding.path) for finding in report.findings] == [
        ("SCHEMA_REQUIRED", "course.title")
    ]


def test_validator_reports_missing_source_reference() -> None:
    document = _minimal_document()
    document["nodes"][0]["source_ids"] = ["40000000-0000-4000-8000-000000000099"]

    report = validate_course_document(document)

    assert ("SOURCE_MISSING", "nodes[0].source_ids[0]") in {
        (finding.code, finding.path) for finding in report.findings
    }


def test_validator_reports_broken_chapter_node_reference() -> None:
    document = _minimal_document()
    document["chapters"][0]["node_ids"] = ["30000000-0000-4000-8000-000000000099"]

    report = validate_course_document(document)

    assert ("REFERENCE_MISSING", "chapters[0].node_ids[0]") in {
        (finding.code, finding.path) for finding in report.findings
    }


def test_validator_reports_prerequisite_cycle() -> None:
    document = _minimal_document()
    document["nodes"][0]["prerequisites"] = [
        "30000000-0000-4000-8000-000000000001"
    ]

    report = validate_course_document(document)

    assert [finding.code for finding in report.findings] == ["PREREQUISITE_CYCLE"]


def test_validator_reports_invalid_mastery_policy_and_test_links() -> None:
    document = _minimal_document()
    document["nodes"][0]["mastery_policy_id"] = (
        "80000000-0000-4000-8000-000000000099"
    )
    document["question_templates"][0]["test_case_ids"] = [
        "70000000-0000-4000-8000-000000000099"
    ]

    report = validate_course_document(document)

    assert {(finding.code, finding.path) for finding in report.findings} == {
        ("MASTERY_POLICY_MISSING", "nodes[0].mastery_policy_id"),
        ("TEST_CASE_MISSING", "question_templates[0].test_case_ids[0]"),
    }


def test_validator_reports_asset_version_conflict() -> None:
    document = _minimal_document()
    document["question_templates"][0]["version"] = "1.1.0"

    report = validate_course_document(document)

    assert [(finding.code, finding.path) for finding in report.findings] == [
        ("VERSION_CONFLICT", "question_templates[0].version")
    ]


def test_validator_reports_declared_course_count_mismatch() -> None:
    document = _minimal_document()
    document["course"]["required_chapter_count"] = 2
    document["course"]["minimum_node_count"] = 2

    report = validate_course_document(document)

    assert {(finding.code, finding.path) for finding in report.findings} == {
        ("CHAPTER_COUNT_INVALID", "chapters"),
        ("NODE_COUNT_INVALID", "nodes"),
    }


def test_schema_generator_exports_every_governed_asset_contract() -> None:
    schemas = generate_asset_schemas()

    assert set(schemas) == {
        "course.schema.json",
        "node.schema.json",
        "source.schema.json",
        "error-pattern.schema.json",
        "question-template.schema.json",
        "test-case.schema.json",
        "mastery-policy.schema.json",
        "course-bundle.schema.json",
    }
    assert schemas["node.schema.json"]["additionalProperties"] is False


def test_published_university_course_is_complete_and_reproducibly_valid() -> None:
    document = json.loads(PUBLISHED_CATALOG.read_text(encoding="utf-8"))
    published_report = json.loads(PUBLISHED_REPORT.read_text(encoding="utf-8"))

    report = validate_course_document(document)

    assert report.valid is True
    assert report.counts == {
        "chapters": 14,
        "nodes": 84,
        "sources": 16,
        "error_patterns": 84,
        "question_templates": 168,
        "test_cases": 168,
        "mastery_policies": 2,
        "deep_units": 4,
    }
    assert report.model_dump(mode="json") == published_report

    nodes_by_id = {node["node_id"]: node for node in document["nodes"]}
    deep_titles = {
        nodes_by_id[node_id]["title"] for node_id in document["course"]["deep_unit_node_ids"]
    }
    assert deep_titles == {
        "循环边界综合调试",
        "UnboundLocalError 深度调试",
        "可变默认参数共享陷阱",
        "调用栈深度追踪",
    }
    assert all(
        source["url"].startswith(("https://docs.python.org/", "https://peps.python.org/"))
        for source in document["sources"]
    )
