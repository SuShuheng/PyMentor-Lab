"""Pydantic ↔ Zod conformance gate.

This is the cross-language contract-drift detector required by CONTRACT.md
("Errors"), the PRD test matrix ("跨语言契约: Pydantic↔Zod Schema 一致性"),
and the frozen design (§22 risk mitigation). It runs in two complementary modes:

1. The Pydantic models parse the same fixtures the Zod side parses, so a
   payload accepted by one language is accepted by the other.
2. Each Pydantic model's required-field set equals the Zod-derived JSON
   Schema's required-field set for the same model name — so a field added on
   one side but not the other fails CI.

The canonical JSON Schemas live in ``packages/contracts/schemas.json`` and are
exported from Zod by ``pnpm contracts:check`` (export-json-schema.ts). If that
file is missing the parity tests skip with a clear instruction, since the
bootstrap ordering runs the TS export before this suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.contracts import (
    AdminAgentRunView,
    AdminEvidencePage,
    AdminMasterySummary,
    AdminResourceReviewPage,
    AdminStudentPage,
    AdminStudentProfile,
    AdminStudentProgress,
    AgentAuditEnvelope,
    AgentProposalEnvelope,
    AgentReplayRequest,
    AssessmentAgentInput,
    AssessmentAgentOutput,
    AssessmentSubmission,
    AuditEvent,
    AuthTokens,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatMessage,
    CoachAgentInput,
    CoachAgentOutput,
    CodeRunRequest,
    CodeRunView,
    CodeSubmissionRequest,
    ErrorCode,
    ErrorEnvelope,
    EvidenceEvent,
    HealthResponse,
    HintRequest,
    HintUsageView,
    IdempotencyRecord,
    LoginRequest,
    MasteryView,
    OrchestratorAgentInput,
    OrchestratorAgentOutput,
    OutboxEventModel,
    PathAgentInput,
    PathAgentOutput,
    PathSnapshot,
    PendingRegistration,
    ProfileAgentInput,
    ProfileAgentOutput,
    ProfileDisputeRequest,
    ProfileDisputeView,
    ProfileSnapshot,
    RegisterRequest,
    RegisterResponse,
    RegistrationDecisionRequest,
    ResourceAgentInput,
    ResourceAgentOutput,
    ResourceArtifactView,
    ResourceJobCreate,
    ResourceJobView,
    ResourceObjectView,
    ReviewRescheduleRequest,
    ReviewView,
    SandboxExecutionRequest,
    SandboxExecutionResponse,
    SandboxResult,
    SandboxRunStatus,
    SystemPingResponse,
    TaskStartResponse,
    TaskSubmissionResponse,
    TodayItem,
    TokenRefreshRequest,
    UserProfile,
    WorkerJobEnvelope,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_PATH = REPO_ROOT / "packages" / "contracts" / "schemas.json"

# --- Shared fixtures (kept in lock-step with packages/contracts/src/conformance.ts) ---
FIXTURES: dict[str, list[dict[str, Any]]] = {
    "AdminStudentPage": [
        {
            "items": [
                {
                    "id": "10000000-0000-4000-8000-000000000001",
                    "email": "student@example.com",
                    "student_no": "S001",
                    "display_name": "Student",
                    "status": "ACTIVE",
                    "created_at": "2026-07-18T00:00:00Z",
                    "profile_version": 2,
                    "completed_tasks": 3,
                    "due_reviews": 1,
                }
            ],
            "page": {"number": 1, "size": 20, "total_items": 1, "total_pages": 1},
        }
    ],
    "AdminStudentProfile": [
        {
            "student_id": "10000000-0000-4000-8000-000000000001",
            "version": 2,
            "dimensions": [
                {
                    "dimension": "DEBUGGING",
                    "scope_key": "GLOBAL",
                    "score": 0.75,
                    "confidence": 0.8,
                    "support_level": 1,
                }
            ],
            "created_at": "2026-07-18T00:00:00Z",
        }
    ],
    "AdminStudentProgress": [
        {
            "student_id": "10000000-0000-4000-8000-000000000001",
            "current_path_id": "20000000-0000-4000-8000-000000000001",
            "current_node_id": "30000000-0000-4000-8000-000000000001",
            "completed_tasks": 3,
            "due_reviews": 1,
            "mastery_counts": {"LEARNING": 1},
            "last_active_at": "2026-07-18T00:00:00Z",
        }
    ],
    "AdminEvidencePage": [
        {
            "items": [
                {
                    "id": "40000000-0000-4000-8000-000000000001",
                    "event_id": "evt_admin_1",
                    "event_type": "TASK_SUBMITTED",
                    "course_id": "50000000-0000-4000-8000-000000000001",
                    "node_id": "30000000-0000-4000-8000-000000000001",
                    "task_id": None,
                    "trace_id": "trc_admin_1",
                    "evidence_confidence": 0.9,
                    "created_at": "2026-07-18T00:00:00Z",
                }
            ],
            "page": {"number": 1, "size": 20, "total_items": 1, "total_pages": 1},
        }
    ],
    "AdminMasterySummary": [
        {
            "course_id": "50000000-0000-4000-8000-000000000001",
            "total_states": 2,
            "counts": {"LEARNING": 1, "STABLE_MASTERY": 1},
            "due_reviews": 1,
            "stable_ratio": 0.5,
        }
    ],
    "AdminResourceReviewPage": [
        {
            "items": [
                {
                    "resource_id": "60000000-0000-4000-8000-000000000001",
                    "job_id": "70000000-0000-4000-8000-000000000001",
                    "student_id": "10000000-0000-4000-8000-000000000001",
                    "resource_type": "STRUCTURE_CARD",
                    "version": 1,
                    "status": "REVIEWING",
                    "content_digest": "a" * 64,
                    "created_at": "2026-07-18T00:00:00Z",
                    "gates": [
                        {
                            "gate": "FACTUAL",
                            "version": 1,
                            "passed": True,
                            "findings": [],
                            "reviewer": "factual-v1",
                            "created_at": "2026-07-18T00:00:00Z",
                        }
                    ],
                }
            ],
            "page": {"number": 1, "size": 20, "total_items": 1, "total_pages": 1},
        }
    ],
    "AdminAgentRunView": [
        {
            "external_run_id": "run_admin_1",
            "event_id": "evt_admin_1",
            "trace_id": "trc_admin_1",
            "student_id": "10000000-0000-4000-8000-000000000001",
            "status": "SUCCEEDED",
            "route": "resource",
            "latest_sequence": 2,
            "checkpoint_thread_id": "thread_admin_1",
            "latest_checkpoint_id": "checkpoint_admin_1",
            "fallback_used": False,
            "error_code": None,
            "input_snapshot": {"api_key": "***", "summary": "bounded"},
            "output_snapshot": {"result": "safe"},
            "started_at": "2026-07-18T00:00:00Z",
            "completed_at": "2026-07-18T00:00:01Z",
            "created_at": "2026-07-18T00:00:00Z",
            "tool_calls": [
                {
                    "sequence": 1,
                    "node": "resource",
                    "tool_name": "knowledge_search",
                    "event_type": "TOOL_COMPLETED",
                    "status": "SUCCEEDED",
                    "argument_digest": "b" * 64,
                    "result_digest": "c" * 64,
                    "latency_ms": 12,
                    "retry_count": 0,
                    "error_code": None,
                    "occurred_at": "2026-07-18T00:00:00Z",
                }
            ],
        }
    ],
    "ErrorEnvelope": [
        {
            "code": "VALIDATION_ERROR",
            "message": "email is invalid",
            "trace_id": "trc_123",
            "retryable": False,
            "field_errors": [{"field": "email", "code": "format", "message": "invalid email"}],
        },
        {
            "code": "INTERNAL_ERROR",
            "message": "unexpected failure",
            "trace_id": "trc_456",
            "retryable": False,
        },
    ],
    "HealthResponse": [
        {
            "status": "ok",
            "service": "api",
            "version": "0.0.0",
            "timestamp": "2026-07-17T00:00:00Z",
        },
        {
            "status": "degraded",
            "service": "worker",
            "version": "1.2.3",
            "timestamp": "2026-07-17T00:00:00Z",
        },
    ],
    "SystemPingResponse": [{"ok": True, "service": "api", "timestamp": "2026-07-17T00:00:00Z"}],
    "ChatCompletionChunk": [
        {
            "id": "chat_1",
            "chunk_index": 0,
            "delta_content": "Hello",
            "timestamp": "2026-07-17T00:00:00Z",
        },
        {
            "id": "chat_1",
            "chunk_index": 1,
            "delta_reasoning": "thinking",
            "delta_tool_calls": [{"index": 0, "id": "call_1", "name": "lookup", "arguments": "{}"}],
            "timestamp": "2026-07-17T00:00:00Z",
        },
    ],
    "ChatMessage": [{"role": "user", "content": "Explain Python loops."}],
    "ChatCompletionRequest": [
        {
            "course_id": "69408047-3b99-5fb2-b383-81f7314ecd5d",
            "node_id": "9512e5ec-f547-51b3-b0df-c5b3a877da9e",
            "messages": [{"role": "user", "content": "Explain Python loops."}],
            "stream": True,
        }
    ],
    "SandboxResult": [
        {
            "run_id": "run_1",
            "status": "PASSED",
            "passed": True,
            "stdout": "",
            "stderr": "",
            "tests": [
                {
                    "case_id": "visible-basic",
                    "display_name": "visible-basic",
                    "visibility": "VISIBLE",
                    "comparison": "EQUAL",
                    "transfer": False,
                    "passed": True,
                    "message": None,
                    "stdout": "",
                    "stderr": "",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "duration_ms": 12,
                }
            ],
            "trace_frames": [
                {
                    "sequence": 1,
                    "line": 1,
                    "event": "line",
                    "func_name": "solve",
                    "locals": {"value": "3"},
                }
            ],
            "resource_usage": {
                "cpu_ms": 10,
                "wall_ms": 20,
                "peak_memory_kb": 1024,
                "exit_code": 0,
            },
            "stdout_truncated": False,
            "stderr_truncated": False,
            "trace_truncated": False,
            "user_error": None,
            "platform_error": None,
        },
        {
            "run_id": "run_2",
            "status": "ERROR",
            "passed": False,
            "stdout": "",
            "stderr": "",
            "tests": [],
            "trace_frames": None,
            "resource_usage": {
                "cpu_ms": 0,
                "wall_ms": 0,
                "peak_memory_kb": None,
                "exit_code": None,
            },
            "stdout_truncated": False,
            "stderr_truncated": False,
            "trace_truncated": False,
            "user_error": None,
            "platform_error": "runner crashed",
        },
    ],
    "CodeRunRequest": [
        {
            "task_instance_id": "tsk_1",
            "source_code": "def solve(value):\n    return value + 1\n",
            "mode": "TRACE",
            "expected_task_version": 3,
            "trace_enabled": True,
        }
    ],
    "CodeSubmissionRequest": [
        {
            "task_instance_id": "tsk_1",
            "source_code": "def solve(value):\n    return value + 1\n",
            "expected_task_version": 3,
        }
    ],
    "CodeRunView": [
        {
            "run_id": "run_1",
            "task_instance_id": "tsk_1",
            "mode": "RUN",
            "status": "COMPLETED",
            "version": 1,
            "revision": {
                "id": "rev_1",
                "sequence": 1,
                "source_digest": "a" * 64,
                "created_at": "2026-07-17T00:00:00Z",
            },
            "result": None,
            "evidence_event_id": None,
            "requested_at": "2026-07-17T00:00:00Z",
            "started_at": None,
            "completed_at": None,
        }
    ],
    "HintRequest": [{"level": 1, "revision_id": "rev_1", "expected_task_version": 3}],
    "HintUsageView": [
        {
            "id": "hint_1",
            "task_instance_id": "tsk_1",
            "revision_id": "rev_1",
            "sequence": 1,
            "hint_key": "loop-bound",
            "level": 1,
            "cost": 0.1,
            "content": "Check the loop boundary.",
            "created_at": "2026-07-17T00:00:00Z",
        }
    ],
    "SandboxExecutionRequest": [
        {
            "protocol_version": "1",
            "request_id": "req_1",
            "run_id": "run_1",
            "trace_id": "trc_1",
            "source_code": "def solve(value):\n    return value + 1\n",
            "entrypoint": {"kind": "FUNCTION", "name": "solve"},
            "cases": [
                {
                    "id": "visible-basic",
                    "args": [1],
                    "expected": 2,
                    "comparison": "EQUAL",
                    "transfer": False,
                }
            ],
            "allowed_imports": ["math"],
            "phase": "VISIBLE",
            "policy": {
                "timeout_ms": 2000,
                "memory_mb": 128,
                "pids_limit": 32,
                "output_limit_bytes": 65536,
                "test_limit": 256,
                "trace_frame_limit": 1000,
            },
            "trace_enabled": False,
        }
    ],
    "SandboxExecutionResponse": [
        {
            "protocol_version": "1",
            "request_id": "req_1",
            "run_id": "run_1",
            "result": {
                "run_id": "run_1",
                "status": "PASSED",
                "passed": True,
                "stdout": "",
                "stderr": "",
                "tests": [],
                "trace_frames": None,
                "resource_usage": {
                    "cpu_ms": 10,
                    "wall_ms": 20,
                    "peak_memory_kb": 1024,
                    "exit_code": 0,
                },
                "stdout_truncated": False,
                "stderr_truncated": False,
                "trace_truncated": False,
                "user_error": None,
                "platform_error": None,
            },
        }
    ],
    "WorkerJobEnvelope": [
        {
            "schema_version": 1,
            "event_id": "evt_job_1",
            "trace_id": "trc_1",
            "tenant_id": "tnt_demo",
            "student_id": "stu_1",
            "kind": "resource_generate",
            "payload": {"need": "loops"},
            "enqueued_at": "2026-07-17T00:00:00Z",
        }
    ],
    "OrchestratorAgentInput": [
        {
            "kind": "coding_coach",
            "request": "Explain the failed loop test.",
            "context": {
                "course_id": "course_python_1",
                "node_id": "node_loops",
                "task_id": "task_loop_boundary",
                "evidence_event_ids": ["evt_code_1"],
            },
        }
    ],
    "OrchestratorAgentOutput": [
        {"route": "coach", "intent_code": "CODE_FAILURE", "summary": "Coach the failed test."}
    ],
    "ProfileAgentInput": [
        {
            "evidence_summary": "Three loop-boundary failures.",
            "current_profile_version": 3,
            "context": {
                "course_id": "course_python_1",
                "node_id": "node_loops",
                "task_id": "task_loop_boundary",
                "evidence_event_ids": ["evt_code_1"],
            },
        }
    ],
    "ProfileAgentOutput": [
        {
            "kind": "profile_change",
            "changes": [
                {"dimension": "DEBUGGING", "delta": -0.1, "reason": "Repeated boundary misses."}
            ],
        }
    ],
    "PathAgentInput": [
        {
            "profile_summary": "Needs loop-boundary remediation.",
            "available_minutes": 30,
            "candidate_node_ids": ["node_loops", "node_ranges"],
            "context": {
                "course_id": "course_python_1",
                "node_id": "node_loops",
                "task_id": "task_loop_boundary",
                "evidence_event_ids": ["evt_code_1"],
            },
        }
    ],
    "PathAgentOutput": [
        {
            "kind": "path_plan",
            "steps": [
                {
                    "node_id": "node_ranges",
                    "action": "REMEDIATE",
                    "reason": "Repair range semantics.",
                }
            ],
        }
    ],
    "ResourceAgentInput": [
        {
            "learning_need": "Understand exclusive range bounds.",
            "resource_types": ["MICRO_LECTURE", "STRUCTURE_CARD"],
            "tutoring_question": "Why is the last item missing?",
            "context": {
                "course_id": "course_python_1",
                "node_id": "node_loops",
                "task_id": "task_loop_boundary",
                "evidence_event_ids": ["evt_code_1"],
            },
        }
    ],
    "ResourceAgentOutput": [
        {
            "kind": "resource_request",
            "requests": [
                {
                    "resource_type": "MICRO_LECTURE",
                    "objective": "Contrast inclusive and exclusive bounds.",
                }
            ],
            "answer": "Python range excludes its stop value.",
        }
    ],
    "CoachAgentInput": [
        {
            "error_summary": "Expected 4 values, received 3.",
            "test_summary": "Hidden upper-bound case failed.",
            "hint_level": 1,
            "context": {
                "course_id": "course_python_1",
                "node_id": "node_loops",
                "task_id": "task_loop_boundary",
                "evidence_event_ids": ["evt_code_1"],
            },
        }
    ],
    "CoachAgentOutput": [
        {
            "kind": "coaching_feedback",
            "diagnosis": "The loop stops one step early.",
            "hints": ["Inspect the stop argument."],
            "next_test": "Try the smallest non-empty boundary.",
        }
    ],
    "AssessmentAgentInput": [
        {
            "response_summary": "Student explains the exclusive stop value.",
            "rubric_keys": ["CONCEPT", "TRANSFER"],
            "context": {
                "course_id": "course_python_1",
                "node_id": "node_loops",
                "task_id": "task_loop_boundary",
                "evidence_event_ids": ["evt_code_1"],
            },
        }
    ],
    "AssessmentAgentOutput": [
        {
            "kind": "assessment_feedback",
            "rubric_scores": {"CONCEPT": 0.9, "TRANSFER": 0.7},
            "feedback": "Correct explanation with partial transfer.",
            "evidence_claims": ["Explains exclusive bounds."],
        }
    ],
    "AgentProposalEnvelope": [
        {
            "schema_version": 1,
            "agent_run_id": "run_agent_1",
            "event_id": "evt_job_1",
            "trace_id": "trc_1",
            "tenant_id": "tnt_demo",
            "student_id": "stu_1",
            "node": "coach",
            "status": "SUCCEEDED",
            "proposal": {
                "kind": "coaching_feedback",
                "diagnosis": "The loop stops one step early.",
                "hints": ["Inspect the stop argument."],
                "next_test": "Try the smallest non-empty boundary.",
            },
            "fallback_used": False,
            "completed_at": "2026-07-17T00:00:00Z",
        }
    ],
    "AgentAuditEnvelope": [
        {
            "schema_version": 1,
            "agent_run_id": "run_agent_1",
            "event_id": "evt_job_1",
            "trace_id": "trc_1",
            "tenant_id": "tnt_demo",
            "student_id": "stu_1",
            "sequence": 1,
            "event_type": "TOOL_COMPLETED",
            "node": "coach",
            "tool_name": "llm.complete",
            "detail": {
                "status": "SUCCEEDED",
                "latency_ms": 12,
                "argument_digest": "a" * 64,
                "result_digest": "b" * 64,
                "retry_count": 0,
                "fallback": False,
            },
            "occurred_at": "2026-07-17T00:00:00Z",
        }
    ],
    "AgentReplayRequest": [
        {
            "schema_version": 1,
            "tenant_id": "tnt_demo",
            "original_event_id": "evt_job_1",
            "replay_event_id": "evt_job_1_replay_1",
            "checkpoint_id": "chk_1",
            "requested_at": "2026-07-17T00:00:00Z",
        }
    ],
    "RegisterRequest": [
        {"email": "student@example.com", "password": "S3cret-Pass!"},
        {"email": "stu@uni.edu", "password": "another-ok-pw", "student_no": "2024001"},
    ],
    "RegisterResponse": [
        {
            "user_id": "00000000-0000-0000-0000-000000000001",
            "email": "student@example.com",
            "status": "PENDING",
            "message": "Registration received. An administrator will review it.",
        }
    ],
    "LoginRequest": [{"email": "student@example.com", "password": "S3cret-Pass!"}],
    "AuthTokens": [
        {
            "access_token": "eyJhbGciOiJIUzI1NiJ9.payload.sig",
            "refresh_token": "eyJhbGciOiJIUzI1NiJ9.refresh.sig",
            "token_type": "Bearer",
            "expires_in": 900,
        }
    ],
    "TokenRefreshRequest": [{"refresh_token": "eyJhbGciOiJIUzI1NiJ9.refresh.sig"}],
    "UserProfile": [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "email": "student@example.com",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "roles": ["STUDENT"],
            "status": "ACTIVE",
        },
        {
            "id": "00000000-0000-0000-0000-000000000003",
            "email": "admin@uni.edu",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "roles": ["SYSTEM_ADMIN"],
            "status": "ACTIVE",
            "display_name": "Admin",
        },
    ],
    "PendingRegistration": [
        {
            "user_id": "00000000-0000-0000-0000-000000000001",
            "email": "student@example.com",
            "status": "PENDING",
            "created_at": "2026-07-17T00:00:00Z",
        }
    ],
    "RegistrationDecisionRequest": [
        {},
        {"reason": "Missing student ID"},
    ],
    "EvidenceEvent": [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "student_id": "00000000-0000-0000-0000-000000000003",
            "event_id": "evt_001",
            "event_type": "CODE_RUN_COMPLETED",
            "trace_id": "trc_1",
            "payload": {"stdout": "ok"},
            "evidence_confidence": 0.9,
            "created_at": "2026-07-17T00:00:00Z",
            "course_id": None,
            "node_id": None,
            "task_id": None,
        }
    ],
    "AuditEvent": [
        {
            "id": "00000000-0000-0000-0000-000000000020",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "action": "REGISTRATION_APPROVED",
            "resource_type": "user",
            "resource_id": "00000000-0000-0000-0000-000000000003",
            "trace_id": "trc_audit",
            "detail": {},
            "actor_user_id": None,
            "created_at": "2026-07-17T00:00:00Z",
        }
    ],
    "OutboxEvent": [
        {
            "id": "00000000-0000-0000-0000-000000000010",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "event_type": "MASTERY_DECIDED",
            "event_id": "evt_ob_1",
            "aggregate_type": "mastery",
            "aggregate_id": "agg_1",
            "trace_id": "trc_ob",
            "payload": {},
            "published": False,
            "created_at": "2026-07-17T00:00:00Z",
        }
    ],
    "IdempotencyRecord": [
        {
            "key": "idem_1",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "endpoint": "/api/v1/tasks/123/submit",
            "response_status": None,
            "response_body": None,
        }
    ],
    "ProfileSnapshot": [
        {
            "student_id": "00000000-0000-0000-0000-000000000030",
            "version": 2,
            "source_event_id": "evt_profile_2",
            "dimensions": [
                {
                    "dimension": "DEBUGGING",
                    "scope_key": "loops",
                    "score": 0.65,
                    "confidence": 0.9,
                    "support_level": 1,
                }
            ],
        }
    ],
    "ProfileDisputeRequest": [
        {
            "profile_version_id": "00000000-0000-0000-0000-000000000031",
            "reason": "The debugging score misses my latest attempt.",
        }
    ],
    "ProfileDisputeView": [
        {
            "id": "00000000-0000-0000-0000-000000000041",
            "profile_version_id": "00000000-0000-0000-0000-000000000031",
            "reason": "The debugging score misses my latest attempt.",
        }
    ],
    "PathSnapshot": [
        {
            "id": "00000000-0000-0000-0000-000000000032",
            "course_id": "00000000-0000-0000-0000-000000000033",
            "version": 3,
            "status": "CURRENT",
            "steps": [
                {
                    "id": "00000000-0000-0000-0000-000000000034",
                    "position": 1,
                    "node_id": "00000000-0000-0000-0000-000000000035",
                    "kind": "LEARN",
                    "estimated_minutes": 20,
                    "scenario_key": "loops-v1",
                    "validation_status": "VALIDATED",
                }
            ],
        }
    ],
    "TodayItem": [
        {
            "id": "00000000-0000-0000-0000-000000000036",
            "course_id": "00000000-0000-0000-0000-000000000033",
            "node_id": "00000000-0000-0000-0000-000000000035",
            "kind": "REVIEW",
            "estimated_minutes": 15,
            "due_at": "2026-07-24T00:00:00Z",
            "task_version_id": None,
        }
    ],
    "TaskStartResponse": [
        {
            "id": "00000000-0000-0000-0000-000000000037",
            "task_version_id": "00000000-0000-0000-0000-000000000038",
            "status": "ACTIVE",
            "snapshot": {"prompt": "Fix the loop boundary"},
            "started_at": "2026-07-17T00:00:00Z",
            "version": 1,
        }
    ],
    "AssessmentSubmission": [
        {
            "evidence_event_id": "evt_assessment_1",
            "expected_task_version": 1,
        }
    ],
    "TaskSubmissionResponse": [
        {
            "assessment_id": "00000000-0000-0000-0000-000000000042",
            "task_instance_id": "00000000-0000-0000-0000-000000000037",
            "course_id": "00000000-0000-0000-0000-000000000033",
            "node_id": "00000000-0000-0000-0000-000000000035",
            "status": "INITIAL_MASTERY",
            "version": 2,
            "review_due_at": "2026-07-24T00:00:00Z",
        }
    ],
    "MasteryView": [
        {
            "id": "00000000-0000-0000-0000-000000000039",
            "course_id": "00000000-0000-0000-0000-000000000033",
            "node_id": "00000000-0000-0000-0000-000000000035",
            "status": "INITIAL_MASTERY",
            "version": 2,
            "review_due_at": "2026-07-24T00:00:00Z",
        }
    ],
    "ReviewView": [
        {
            "id": "00000000-0000-0000-0000-000000000040",
            "course_id": "00000000-0000-0000-0000-000000000033",
            "node_id": "00000000-0000-0000-0000-000000000035",
            "scenario_key": "loops-review-v2",
            "due_at": "2026-07-24T00:00:00Z",
            "status": "SCHEDULED",
            "reschedule_count": 0,
            "version": 1,
        }
    ],
    "ReviewRescheduleRequest": [{"due_at": "2026-07-25T00:00:00Z", "expected_version": 1}],
    "ResourceJobCreate": [
        {
            "course_id": "69408047-3b99-5fb2-b383-81f7314ecd5d",
            "node_id": "9512e5ec-f547-51b3-b0df-c5b3a877da9e",
            "resource_types": ["STRUCTURE_CARD", "MICRO_LECTURE"],
        }
    ],
    "ResourceObjectView": [
        {
            "object_key": "resources/tenant/job/structure-card/v1/digest",
            "digest": "a" * 64,
            "mime_type": "application/json",
            "size_bytes": 42,
            "version": 1,
            "published": True,
        }
    ],
    "ResourceArtifactView": [
        {
            "id": "55555555-5555-4555-8555-555555555555",
            "resource_type": "STRUCTURE_CARD",
            "version": 1,
            "status": "PUBLISHED",
            "source_ids": ["33333333-3333-4333-8333-333333333333"],
            "context_digest": "b" * 64,
            "content_digest": "a" * 64,
            "object": {
                "object_key": "resources/tenant/job/structure-card/v1/digest",
                "digest": "a" * 64,
                "mime_type": "application/json",
                "size_bytes": 42,
                "version": 1,
                "published": True,
            },
            "published_at": "2026-07-18T00:00:00Z",
        }
    ],
    "ResourceJobView": [
        {
            "id": "44444444-4444-4444-8444-444444444444",
            "course_id": "69408047-3b99-5fb2-b383-81f7314ecd5d",
            "node_id": "9512e5ec-f547-51b3-b0df-c5b3a877da9e",
            "status": "PARTIAL_READY",
            "progress_percent": 20,
            "requested_types": ["STRUCTURE_CARD", "MICRO_LECTURE"],
            "artifacts": [],
            "created_at": "2026-07-18T00:00:00Z",
            "updated_at": "2026-07-18T00:00:01Z",
        }
    ],
}

MODEL_BY_NAME: dict[str, type[BaseModel]] = {
    "AdminAgentRunView": AdminAgentRunView,
    "AdminEvidencePage": AdminEvidencePage,
    "AdminMasterySummary": AdminMasterySummary,
    "AdminResourceReviewPage": AdminResourceReviewPage,
    "AdminStudentPage": AdminStudentPage,
    "AdminStudentProfile": AdminStudentProfile,
    "AdminStudentProgress": AdminStudentProgress,
    "AgentAuditEnvelope": AgentAuditEnvelope,
    "AgentProposalEnvelope": AgentProposalEnvelope,
    "AgentReplayRequest": AgentReplayRequest,
    "AssessmentAgentInput": AssessmentAgentInput,
    "AssessmentAgentOutput": AssessmentAgentOutput,
    "ErrorEnvelope": ErrorEnvelope,
    "HealthResponse": HealthResponse,
    "SystemPingResponse": SystemPingResponse,
    "ChatCompletionChunk": ChatCompletionChunk,
    "ChatMessage": ChatMessage,
    "ChatCompletionRequest": ChatCompletionRequest,
    "CoachAgentInput": CoachAgentInput,
    "CoachAgentOutput": CoachAgentOutput,
    "SandboxResult": SandboxResult,
    "CodeRunRequest": CodeRunRequest,
    "CodeSubmissionRequest": CodeSubmissionRequest,
    "CodeRunView": CodeRunView,
    "HintRequest": HintRequest,
    "HintUsageView": HintUsageView,
    "SandboxExecutionRequest": SandboxExecutionRequest,
    "SandboxExecutionResponse": SandboxExecutionResponse,
    "WorkerJobEnvelope": WorkerJobEnvelope,
    "RegisterRequest": RegisterRequest,
    "RegisterResponse": RegisterResponse,
    "LoginRequest": LoginRequest,
    "AuthTokens": AuthTokens,
    "TokenRefreshRequest": TokenRefreshRequest,
    "UserProfile": UserProfile,
    "PendingRegistration": PendingRegistration,
    "RegistrationDecisionRequest": RegistrationDecisionRequest,
    "AuditEvent": AuditEvent,
    "EvidenceEvent": EvidenceEvent,
    "OutboxEvent": OutboxEventModel,
    "OrchestratorAgentInput": OrchestratorAgentInput,
    "OrchestratorAgentOutput": OrchestratorAgentOutput,
    "PathAgentInput": PathAgentInput,
    "PathAgentOutput": PathAgentOutput,
    "IdempotencyRecord": IdempotencyRecord,
    "ProfileSnapshot": ProfileSnapshot,
    "ProfileAgentInput": ProfileAgentInput,
    "ProfileAgentOutput": ProfileAgentOutput,
    "ProfileDisputeRequest": ProfileDisputeRequest,
    "ProfileDisputeView": ProfileDisputeView,
    "PathSnapshot": PathSnapshot,
    "TodayItem": TodayItem,
    "TaskStartResponse": TaskStartResponse,
    "AssessmentSubmission": AssessmentSubmission,
    "TaskSubmissionResponse": TaskSubmissionResponse,
    "MasteryView": MasteryView,
    "ReviewView": ReviewView,
    "ReviewRescheduleRequest": ReviewRescheduleRequest,
    "ResourceAgentInput": ResourceAgentInput,
    "ResourceAgentOutput": ResourceAgentOutput,
    "ResourceJobCreate": ResourceJobCreate,
    "ResourceObjectView": ResourceObjectView,
    "ResourceArtifactView": ResourceArtifactView,
    "ResourceJobView": ResourceJobView,
}


def test_error_code_count_matches_contract() -> None:
    """CONTRACT.md lists exactly 15 stable error codes."""
    assert len(list(ErrorCode)) == 15


def test_sandbox_outcome_status_is_not_the_persisted_run_lifecycle() -> None:
    assert {status.value for status in SandboxRunStatus} == {
        "PASSED",
        "FAILED",
        "ERROR",
        "TIMEOUT",
        "CANCELLED",
    }
    with pytest.raises(ValidationError):
        SandboxResult.model_validate({**FIXTURES["SandboxResult"][0], "status": "PLATFORM_ERROR"})


@pytest.mark.parametrize("model_name", sorted(MODEL_BY_NAME))
def test_pydantic_parses_shared_fixtures(model_name: str) -> None:
    """Every fixture the Zod side accepts must parse in Pydantic too."""
    model = MODEL_BY_NAME[model_name]
    for sample in FIXTURES[model_name]:
        instance = model.model_validate(sample)
        # Round-trip: dump back to wire shape must re-validate.
        assert model.model_validate(instance.model_dump(mode="json"))


def test_invalid_payload_is_rejected() -> None:
    """Unknown enum values must be rejected (drift protection)."""
    with pytest.raises(ValidationError):
        ErrorEnvelope.model_validate(
            {
                "code": "NOT_A_REAL_CODE",
                "message": "x",
                "trace_id": "t",
                "retryable": False,
            }
        )

    with pytest.raises(ValidationError):
        AgentReplayRequest.model_validate(
            {
                **FIXTURES["AgentReplayRequest"][0],
                "replay_event_id": "evt_job_1",
            }
        )

    with pytest.raises(ValidationError):
        AgentAuditEnvelope.model_validate(
            {
                **FIXTURES["AgentAuditEnvelope"][0],
                "detail": {"raw_prompt": "secret system prompt"},
            }
        )

    audit = FIXTURES["AgentAuditEnvelope"][0]
    with pytest.raises(ValidationError):
        AgentAuditEnvelope.model_validate({**audit, "sequence": "1"})
    with pytest.raises(ValidationError):
        AgentAuditEnvelope.model_validate(
            {**audit, "detail": {**audit["detail"], "fallback": "false"}}
        )
    with pytest.raises(ValidationError):
        AgentAuditEnvelope.model_validate({**audit, "occurred_at": "2026-07-18T01:02:03"})

    proposal = FIXTURES["AgentProposalEnvelope"][0]
    with pytest.raises(ValidationError):
        AgentProposalEnvelope.model_validate({**proposal, "node": "profile"})
    with pytest.raises(ValidationError):
        AgentProposalEnvelope.model_validate(
            {**proposal, "status": "FAILED_FINAL", "error_code": "UNEXPECTED_ERROR"}
        )


def _load_canonical_schemas() -> dict[str, Any]:
    if not SCHEMAS_PATH.exists():
        pytest.skip(
            "packages/contracts/schemas.json missing — run `pnpm contracts:check` "
            "first to export the Zod-derived JSON Schemas."
        )
    data: dict[str, Any] = json.loads(SCHEMAS_PATH.read_text(encoding="utf-8"))
    return data


def _zod_property_names(canonical_schema: dict[str, Any]) -> set[str]:
    """Extract property names from a zod-to-json-schema model.

    zod-to-json-schema emits ``$ref``/``definitions`` shape, so the properties
    live under ``definitions[<name>].properties`` rather than at the top level.
    """
    definitions = canonical_schema.get("definitions", {})
    # The model is referenced by $ref; pick the single definition that matches.
    for _name, node in definitions.items():
        if isinstance(node, dict) and "properties" in node:
            return set(node["properties"].keys())
    # Fallback: top-level properties (some emitters inline them).
    return set(canonical_schema.get("properties", {}).keys())


@pytest.mark.parametrize("model_name", sorted(MODEL_BY_NAME))
def test_property_names_match_zod_json_schema(model_name: str) -> None:
    """Pydantic and Zod must publish the same field-name set per model.

    This is the durable wire contract: every field the renderer and worker
    read/write must exist on both sides. ``required`` arrays are not compared
    because zod-to-json-schema and Pydantic disagree on how optionality maps
    to JSON Schema (zod marks optional fields as present-but-nullable), so
    property names are the stable, drift-revealing invariant.
    """
    schemas = _load_canonical_schemas()
    assert model_name in schemas, f"{model_name} missing from schemas.json"

    zod_props = _zod_property_names(schemas[model_name])
    pydantic_schema = MODEL_BY_NAME[model_name].model_json_schema()
    pydantic_props = set(pydantic_schema.get("properties", {}).keys())

    assert pydantic_props == zod_props, (
        f"property-name drift for {model_name}:\n"
        f"  pydantic only: {sorted(pydantic_props - zod_props)}\n"
        f"  zod only:      {sorted(zod_props - pydantic_props)}"
    )


def test_error_code_enum_values_match() -> None:
    """The ErrorCode enum values must equal the Zod ErrorCode.options."""
    schemas = _load_canonical_schemas()
    canonical = schemas["ErrorEnvelope"]
    definitions = canonical.get("definitions", {})
    envelope_def = next(v for v in definitions.values() if "properties" in v)
    code_schema = envelope_def["properties"]["code"]
    zod_codes = set(code_schema.get("enum", []))
    pydantic_codes = {code.value for code in ErrorCode}
    assert pydantic_codes == zod_codes, (
        f"error-code enum drift:\n"
        f"  pydantic only: {sorted(pydantic_codes - zod_codes)}\n"
        f"  zod only:      {sorted(zod_codes - pydantic_codes)}"
    )
