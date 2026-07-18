"""Versioned knowledge-asset contract and validation tests for BE-009."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.knowledge_assets import validate_course_document


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
        "error_patterns": [],
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

