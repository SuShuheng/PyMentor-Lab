/**
 * Conformance gate: every published contract model must parse a shared fixture
 * set, and the Zod-derived JSON Schema must equal the canonical committed
 * `schemas.json`. The Python Pydantic mirror runs an identical fixture set
 * (see `backend/tests/test_contracts_parity.py`) and compares against the same
 * JSON Schemas, so a field drift fails on at least one side.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import {
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
  AssessmentSubmission,
  AssessmentAgentInput,
  AssessmentAgentOutput,
  AuthTokens,
  AuditEvent,
  ChatCompletionChunk,
  ChatCompletionRequest,
  ChatMessage,
  CoachAgentInput,
  CoachAgentOutput,
  CodeRunRequest,
  CodeRunView,
  CodeSubmissionRequest,
  ErrorEnvelope,
  EvidenceEvent,
  HealthResponse,
  HintRequest,
  HintUsageView,
  IdempotencyRecord,
  LoginRequest,
  MasteryView,
  OutboxEvent,
  OrchestratorAgentInput,
  OrchestratorAgentOutput,
  PathAgentInput,
  PathAgentOutput,
  PathSnapshot,
  PendingRegistration,
  ProfileDisputeRequest,
  ProfileDisputeView,
  ProfileSnapshot,
  ProfileAgentInput,
  ProfileAgentOutput,
  RegisterRequest,
  RegisterResponse,
  RegistrationDecisionRequest,
  ReviewRescheduleRequest,
  ReviewView,
  ResourceAgentInput,
  ResourceAgentOutput,
  ResourceArtifactView,
  ResourceJobCreate,
  ResourceJobView,
  ResourceObjectView,
  SandboxExecutionRequest,
  SandboxExecutionResponse,
  SandboxResult,
  StreamEvent,
  SystemPingResponse,
  TaskStartResponse,
  TaskSubmissionResponse,
  TodayItem,
  TokenRefreshRequest,
  UserProfile,
  WorkerJobEnvelope,
} from "./index.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SCHEMAS_PATH = resolve(__dirname, "..", "schemas.json");

type Cases = Record<string, { schema: unknown; samples: unknown[] }>;

const agentContext = {
  course_id: "course_python_1",
  node_id: "node_loops",
  task_id: "task_loop_boundary",
  evidence_event_ids: ["evt_code_1"],
};

const cases: Cases = {
  AdminStudentPage: {
    schema: AdminStudentPage,
    samples: [
      {
        items: [
          {
            id: "10000000-0000-4000-8000-000000000001",
            email: "student@example.com",
            student_no: "S001",
            display_name: "Student",
            status: "ACTIVE",
            created_at: "2026-07-18T00:00:00Z",
            profile_version: 2,
            completed_tasks: 3,
            due_reviews: 1,
          },
        ],
        page: { number: 1, size: 20, total_items: 1, total_pages: 1 },
      },
    ],
  },
  AdminStudentProfile: {
    schema: AdminStudentProfile,
    samples: [
      {
        student_id: "10000000-0000-4000-8000-000000000001",
        version: 2,
        dimensions: [
          {
            dimension: "DEBUGGING",
            scope_key: "GLOBAL",
            score: 0.75,
            confidence: 0.8,
            support_level: 1,
          },
        ],
        created_at: "2026-07-18T00:00:00Z",
      },
    ],
  },
  AdminStudentProgress: {
    schema: AdminStudentProgress,
    samples: [
      {
        student_id: "10000000-0000-4000-8000-000000000001",
        current_path_id: "20000000-0000-4000-8000-000000000001",
        current_node_id: "30000000-0000-4000-8000-000000000001",
        completed_tasks: 3,
        due_reviews: 1,
        mastery_counts: { LEARNING: 1 },
        last_active_at: "2026-07-18T00:00:00Z",
      },
    ],
  },
  AdminEvidencePage: {
    schema: AdminEvidencePage,
    samples: [
      {
        items: [
          {
            id: "40000000-0000-4000-8000-000000000001",
            event_id: "evt_admin_1",
            event_type: "TASK_SUBMITTED",
            course_id: "50000000-0000-4000-8000-000000000001",
            node_id: "30000000-0000-4000-8000-000000000001",
            task_id: null,
            trace_id: "trc_admin_1",
            evidence_confidence: 0.9,
            created_at: "2026-07-18T00:00:00Z",
          },
        ],
        page: { number: 1, size: 20, total_items: 1, total_pages: 1 },
      },
    ],
  },
  AdminMasterySummary: {
    schema: AdminMasterySummary,
    samples: [
      {
        course_id: "50000000-0000-4000-8000-000000000001",
        total_states: 2,
        counts: { LEARNING: 1, STABLE_MASTERY: 1 },
        due_reviews: 1,
        stable_ratio: 0.5,
      },
    ],
  },
  AdminResourceReviewPage: {
    schema: AdminResourceReviewPage,
    samples: [
      {
        items: [
          {
            resource_id: "60000000-0000-4000-8000-000000000001",
            job_id: "70000000-0000-4000-8000-000000000001",
            student_id: "10000000-0000-4000-8000-000000000001",
            resource_type: "STRUCTURE_CARD",
            version: 1,
            status: "REVIEWING",
            content_digest: "a".repeat(64),
            created_at: "2026-07-18T00:00:00Z",
            gates: [
              {
                gate: "FACTUAL",
                version: 1,
                passed: true,
                findings: [],
                reviewer: "factual-v1",
                created_at: "2026-07-18T00:00:00Z",
              },
            ],
          },
        ],
        page: { number: 1, size: 20, total_items: 1, total_pages: 1 },
      },
    ],
  },
  AdminAgentRunView: {
    schema: AdminAgentRunView,
    samples: [
      {
        external_run_id: "run_admin_1",
        event_id: "evt_admin_1",
        trace_id: "trc_admin_1",
        student_id: "10000000-0000-4000-8000-000000000001",
        status: "SUCCEEDED",
        route: "resource",
        latest_sequence: 2,
        checkpoint_thread_id: "thread_admin_1",
        latest_checkpoint_id: "checkpoint_admin_1",
        fallback_used: false,
        error_code: null,
        input_snapshot: { api_key: "***", summary: "bounded" },
        output_snapshot: { result: "safe" },
        started_at: "2026-07-18T00:00:00Z",
        completed_at: "2026-07-18T00:00:01Z",
        created_at: "2026-07-18T00:00:00Z",
        tool_calls: [
          {
            sequence: 1,
            node: "resource",
            tool_name: "knowledge_search",
            event_type: "TOOL_COMPLETED",
            status: "SUCCEEDED",
            argument_digest: "b".repeat(64),
            result_digest: "c".repeat(64),
            latency_ms: 12,
            retry_count: 0,
            error_code: null,
            occurred_at: "2026-07-18T00:00:00Z",
          },
        ],
      },
    ],
  },
  ErrorEnvelope: {
    schema: ErrorEnvelope,
    samples: [
      {
        code: "VALIDATION_ERROR",
        message: "email is invalid",
        trace_id: "trc_123",
        retryable: false,
        field_errors: [{ field: "email", code: "format", message: "invalid email" }],
      },
      {
        code: "INTERNAL_ERROR",
        message: "unexpected failure",
        trace_id: "trc_456",
        retryable: false,
      },
    ],
  },
  HealthResponse: {
    schema: HealthResponse,
    samples: [
      { status: "ok", service: "api", version: "0.0.0", timestamp: "2026-07-17T00:00:00Z" },
      {
        status: "degraded",
        service: "worker",
        version: "1.2.3",
        timestamp: "2026-07-17T00:00:00Z",
      },
    ],
  },
  SystemPingResponse: {
    schema: SystemPingResponse,
    samples: [{ ok: true, service: "api", timestamp: "2026-07-17T00:00:00Z" }],
  },
  ChatCompletionChunk: {
    schema: ChatCompletionChunk,
    samples: [
      {
        id: "chat_1",
        chunk_index: 0,
        delta_content: "Hello",
        timestamp: "2026-07-17T00:00:00Z",
      },
      {
        id: "chat_1",
        chunk_index: 1,
        delta_reasoning: "thinking",
        delta_tool_calls: [{ index: 0, id: "call_1", name: "lookup", arguments: "{}" }],
        timestamp: "2026-07-17T00:00:00Z",
      },
    ],
  },
  ChatMessage: {
    schema: ChatMessage,
    samples: [{ role: "user", content: "Explain Python loops." }],
  },
  ChatCompletionRequest: {
    schema: ChatCompletionRequest,
    samples: [
      {
        course_id: "69408047-3b99-5fb2-b383-81f7314ecd5d",
        node_id: "9512e5ec-f547-51b3-b0df-c5b3a877da9e",
        messages: [{ role: "user", content: "Explain Python loops." }],
        stream: true,
      },
    ],
  },
  StreamEvent: {
    schema: StreamEvent,
    samples: [
      {
        type: "content_delta",
        event_id: "evt_1",
        chunk: {
          id: "chat_1",
          chunk_index: 0,
          delta_content: "Hi",
          timestamp: "2026-07-17T00:00:00Z",
        },
      },
      { type: "done", event_id: "evt_2" },
      {
        type: "progress",
        event_id: "evt_3",
        message: "halfway",
        percent: 50,
      },
    ],
  },
  SandboxResult: {
    schema: SandboxResult,
    samples: [
      {
        run_id: "run_1",
        status: "PASSED",
        passed: true,
        stdout: "",
        stderr: "",
        tests: [
          {
            case_id: "visible-basic",
            display_name: "visible-basic",
            visibility: "VISIBLE",
            comparison: "EQUAL",
            transfer: false,
            passed: true,
            message: null,
            stdout: "",
            stderr: "",
            stdout_truncated: false,
            stderr_truncated: false,
            duration_ms: 12,
          },
        ],
        trace_frames: [
          {
            sequence: 1,
            line: 1,
            event: "line",
            func_name: "solve",
            locals: { value: "3" },
          },
        ],
        resource_usage: {
          cpu_ms: 10,
          wall_ms: 20,
          peak_memory_kb: 1024,
          exit_code: 0,
        },
        stdout_truncated: false,
        stderr_truncated: false,
        trace_truncated: false,
        user_error: null,
        platform_error: null,
      },
      {
        run_id: "run_2",
        status: "ERROR",
        passed: false,
        stdout: "",
        stderr: "",
        tests: [],
        trace_frames: null,
        resource_usage: {
          cpu_ms: 0,
          wall_ms: 0,
          peak_memory_kb: null,
          exit_code: null,
        },
        stdout_truncated: false,
        stderr_truncated: false,
        trace_truncated: false,
        user_error: null,
        platform_error: "runner crashed",
      },
    ],
  },
  CodeRunRequest: {
    schema: CodeRunRequest,
    samples: [
      {
        task_instance_id: "tsk_1",
        source_code: "def solve(value):\n    return value + 1\n",
        mode: "TRACE",
        expected_task_version: 3,
        trace_enabled: true,
      },
    ],
  },
  CodeSubmissionRequest: {
    schema: CodeSubmissionRequest,
    samples: [
      {
        task_instance_id: "tsk_1",
        source_code: "def solve(value):\n    return value + 1\n",
        expected_task_version: 3,
      },
    ],
  },
  CodeRunView: {
    schema: CodeRunView,
    samples: [
      {
        run_id: "run_1",
        task_instance_id: "tsk_1",
        mode: "RUN",
        status: "COMPLETED",
        version: 1,
        revision: {
          id: "rev_1",
          sequence: 1,
          source_digest: "a".repeat(64),
          created_at: "2026-07-17T00:00:00Z",
        },
        result: null,
        evidence_event_id: null,
        requested_at: "2026-07-17T00:00:00Z",
        started_at: null,
        completed_at: null,
      },
    ],
  },
  HintRequest: {
    schema: HintRequest,
    samples: [{ level: 1, revision_id: "rev_1", expected_task_version: 3 }],
  },
  HintUsageView: {
    schema: HintUsageView,
    samples: [
      {
        id: "hint_1",
        task_instance_id: "tsk_1",
        revision_id: "rev_1",
        sequence: 1,
        hint_key: "loop-bound",
        level: 1,
        cost: 0.1,
        content: "Check the loop boundary.",
        created_at: "2026-07-17T00:00:00Z",
      },
    ],
  },
  SandboxExecutionRequest: {
    schema: SandboxExecutionRequest,
    samples: [
      {
        protocol_version: "1",
        request_id: "req_1",
        run_id: "run_1",
        trace_id: "trc_1",
        source_code: "def solve(value):\n    return value + 1\n",
        entrypoint: { kind: "FUNCTION", name: "solve" },
        cases: [
          {
            id: "visible-basic",
            args: [1],
            expected: 2,
            comparison: "EQUAL",
            transfer: false,
          },
        ],
        allowed_imports: ["math"],
        phase: "VISIBLE",
        policy: {
          timeout_ms: 2000,
          memory_mb: 128,
          pids_limit: 32,
          output_limit_bytes: 65536,
          test_limit: 256,
          trace_frame_limit: 1000,
        },
        trace_enabled: false,
      },
    ],
  },
  SandboxExecutionResponse: {
    schema: SandboxExecutionResponse,
    samples: [
      {
        protocol_version: "1",
        request_id: "req_1",
        run_id: "run_1",
        result: {
          run_id: "run_1",
          status: "PASSED",
          passed: true,
          stdout: "",
          stderr: "",
          tests: [],
          trace_frames: null,
          resource_usage: {
            cpu_ms: 10,
            wall_ms: 20,
            peak_memory_kb: 1024,
            exit_code: 0,
          },
          stdout_truncated: false,
          stderr_truncated: false,
          trace_truncated: false,
          user_error: null,
          platform_error: null,
        },
      },
    ],
  },
  WorkerJobEnvelope: {
    schema: WorkerJobEnvelope,
    samples: [
      {
        schema_version: 1,
        event_id: "evt_job_1",
        trace_id: "trc_1",
        tenant_id: "tnt_demo",
        student_id: "stu_1",
        kind: "resource_generate",
        payload: { need: "loops" },
        enqueued_at: "2026-07-17T00:00:00Z",
      },
    ],
  },
  OrchestratorAgentInput: {
    schema: OrchestratorAgentInput,
    samples: [{ kind: "coding_coach", request: "Explain the failed loop test.", context: agentContext }],
  },
  OrchestratorAgentOutput: {
    schema: OrchestratorAgentOutput,
    samples: [{ route: "coach", intent_code: "CODE_FAILURE", summary: "Coach the failed test." }],
  },
  ProfileAgentInput: {
    schema: ProfileAgentInput,
    samples: [
      { evidence_summary: "Three loop-boundary failures.", current_profile_version: 3, context: agentContext },
    ],
  },
  ProfileAgentOutput: {
    schema: ProfileAgentOutput,
    samples: [
      {
        kind: "profile_change",
        changes: [
          { dimension: "DEBUGGING", delta: -0.1, reason: "Repeated boundary misses." },
        ],
      },
    ],
  },
  PathAgentInput: {
    schema: PathAgentInput,
    samples: [
      {
        profile_summary: "Needs loop-boundary remediation.",
        available_minutes: 30,
        candidate_node_ids: ["node_loops", "node_ranges"],
        context: agentContext,
      },
    ],
  },
  PathAgentOutput: {
    schema: PathAgentOutput,
    samples: [
      {
        kind: "path_plan",
        steps: [
          { node_id: "node_ranges", action: "REMEDIATE", reason: "Repair range semantics." },
        ],
      },
    ],
  },
  ResourceAgentInput: {
    schema: ResourceAgentInput,
    samples: [
      {
        learning_need: "Understand exclusive range bounds.",
        resource_types: ["MICRO_LECTURE", "STRUCTURE_CARD"],
        tutoring_question: "Why is the last item missing?",
        context: agentContext,
      },
    ],
  },
  ResourceAgentOutput: {
    schema: ResourceAgentOutput,
    samples: [
      {
        kind: "resource_request",
        requests: [
          {
            resource_type: "MICRO_LECTURE",
            objective: "Contrast inclusive and exclusive bounds.",
          },
        ],
        answer: "Python range excludes its stop value.",
      },
    ],
  },
  ResourceJobCreate: {
    schema: ResourceJobCreate,
    samples: [
      {
        course_id: "69408047-3b99-5fb2-b383-81f7314ecd5d",
        node_id: "9512e5ec-f547-51b3-b0df-c5b3a877da9e",
        resource_types: ["STRUCTURE_CARD", "MICRO_LECTURE"],
      },
    ],
  },
  ResourceObjectView: {
    schema: ResourceObjectView,
    samples: [
      {
        object_key: "resources/tenant/job/structure-card/v1/digest",
        digest: "a".repeat(64),
        mime_type: "application/json",
        size_bytes: 42,
        version: 1,
        published: true,
      },
    ],
  },
  ResourceArtifactView: {
    schema: ResourceArtifactView,
    samples: [
      {
        id: "55555555-5555-4555-8555-555555555555",
        resource_type: "STRUCTURE_CARD",
        version: 1,
        status: "PUBLISHED",
        source_ids: ["33333333-3333-4333-8333-333333333333"],
        context_digest: "b".repeat(64),
        content_digest: "a".repeat(64),
        object: {
          object_key: "resources/tenant/job/structure-card/v1/digest",
          digest: "a".repeat(64),
          mime_type: "application/json",
          size_bytes: 42,
          version: 1,
          published: true,
        },
        published_at: "2026-07-18T00:00:00Z",
      },
    ],
  },
  ResourceJobView: {
    schema: ResourceJobView,
    samples: [
      {
        id: "44444444-4444-4444-8444-444444444444",
        course_id: "69408047-3b99-5fb2-b383-81f7314ecd5d",
        node_id: "9512e5ec-f547-51b3-b0df-c5b3a877da9e",
        status: "PARTIAL_READY",
        progress_percent: 20,
        requested_types: ["STRUCTURE_CARD", "MICRO_LECTURE"],
        artifacts: [],
        created_at: "2026-07-18T00:00:00Z",
        updated_at: "2026-07-18T00:00:01Z",
      },
    ],
  },
  CoachAgentInput: {
    schema: CoachAgentInput,
    samples: [
      {
        error_summary: "Expected 4 values, received 3.",
        test_summary: "Hidden upper-bound case failed.",
        hint_level: 1,
        context: agentContext,
      },
    ],
  },
  CoachAgentOutput: {
    schema: CoachAgentOutput,
    samples: [
      {
        kind: "coaching_feedback",
        diagnosis: "The loop stops one step early.",
        hints: ["Inspect the stop argument."],
        next_test: "Try the smallest non-empty boundary.",
      },
    ],
  },
  AssessmentAgentInput: {
    schema: AssessmentAgentInput,
    samples: [
      {
        response_summary: "Student explains the exclusive stop value.",
        rubric_keys: ["CONCEPT", "TRANSFER"],
        context: agentContext,
      },
    ],
  },
  AssessmentAgentOutput: {
    schema: AssessmentAgentOutput,
    samples: [
      {
        kind: "assessment_feedback",
        rubric_scores: { CONCEPT: 0.9, TRANSFER: 0.7 },
        feedback: "Correct explanation with partial transfer.",
        evidence_claims: ["Explains exclusive bounds."],
      },
    ],
  },
  AgentProposalEnvelope: {
    schema: AgentProposalEnvelope,
    samples: [
      {
        schema_version: 1,
        agent_run_id: "run_agent_1",
        event_id: "evt_job_1",
        trace_id: "trc_1",
        tenant_id: "tnt_demo",
        student_id: "stu_1",
        node: "coach",
        status: "SUCCEEDED",
        proposal: {
          kind: "coaching_feedback",
          diagnosis: "The loop stops one step early.",
          hints: ["Inspect the stop argument."],
          next_test: "Try the smallest non-empty boundary.",
        },
        fallback_used: false,
        completed_at: "2026-07-17T00:00:00Z",
      },
    ],
  },
  AgentAuditEnvelope: {
    schema: AgentAuditEnvelope,
    samples: [
      {
        schema_version: 1,
        agent_run_id: "run_agent_1",
        event_id: "evt_job_1",
        trace_id: "trc_1",
        tenant_id: "tnt_demo",
        student_id: "stu_1",
        sequence: 1,
        event_type: "TOOL_COMPLETED",
        node: "coach",
        tool_name: "llm.complete",
        detail: {
          status: "SUCCEEDED",
          latency_ms: 12,
          argument_digest: "a".repeat(64),
          result_digest: "b".repeat(64),
          retry_count: 0,
          fallback: false,
        },
        occurred_at: "2026-07-17T00:00:00Z",
      },
    ],
  },
  AgentReplayRequest: {
    schema: AgentReplayRequest,
    samples: [
      {
        schema_version: 1,
        tenant_id: "tnt_demo",
        original_event_id: "evt_job_1",
        replay_event_id: "evt_job_1_replay_1",
        checkpoint_id: "chk_1",
        requested_at: "2026-07-17T00:00:00Z",
      },
    ],
  },
  RegisterRequest: {
    schema: RegisterRequest,
    samples: [
      { email: "student@example.com", password: "S3cret-Pass!" },
      { email: "stu@uni.edu", password: "another-ok-pw", student_no: "2024001" },
    ],
  },
  RegisterResponse: {
    schema: RegisterResponse,
    samples: [
      {
        user_id: "00000000-0000-0000-0000-000000000001",
        email: "student@example.com",
        status: "PENDING",
        message: "Registration received. An administrator will review it.",
      },
    ],
  },
  LoginRequest: {
    schema: LoginRequest,
    samples: [{ email: "student@example.com", password: "S3cret-Pass!" }],
  },
  AuthTokens: {
    schema: AuthTokens,
    samples: [
      {
        access_token: "eyJhbGciOiJIUzI1NiJ9.payload.sig",
        refresh_token: "eyJhbGciOiJIUzI1NiJ9.refresh.sig",
        token_type: "Bearer",
        expires_in: 900,
      },
    ],
  },
  TokenRefreshRequest: {
    schema: TokenRefreshRequest,
    samples: [{ refresh_token: "eyJhbGciOiJIUzI1NiJ9.refresh.sig" }],
  },
  UserProfile: {
    schema: UserProfile,
    samples: [
      {
        id: "00000000-0000-0000-0000-000000000001",
        email: "student@example.com",
        tenant_id: "00000000-0000-0000-0000-000000000002",
        roles: ["STUDENT"],
        status: "ACTIVE",
      },
      {
        id: "00000000-0000-0000-0000-000000000003",
        email: "admin@uni.edu",
        tenant_id: "00000000-0000-0000-0000-000000000002",
        roles: ["SYSTEM_ADMIN"],
        status: "ACTIVE",
        display_name: "Admin",
      },
    ],
  },
  PendingRegistration: {
    schema: PendingRegistration,
    samples: [
      {
        user_id: "00000000-0000-0000-0000-000000000001",
        email: "student@example.com",
        status: "PENDING",
        created_at: "2026-07-17T00:00:00Z",
      },
    ],
  },
  RegistrationDecisionRequest: {
    schema: RegistrationDecisionRequest,
    samples: [{}, { reason: "Missing student ID" }],
  },
  EvidenceEvent: {
    schema: EvidenceEvent,
    samples: [
      {
        id: "00000000-0000-0000-0000-000000000001",
        tenant_id: "00000000-0000-0000-0000-000000000002",
        student_id: "00000000-0000-0000-0000-000000000003",
        event_id: "evt_001",
        event_type: "CODE_RUN_COMPLETED",
        trace_id: "trc_1",
        payload: { stdout: "ok" },
        evidence_confidence: 0.9,
        created_at: "2026-07-17T00:00:00Z",
        course_id: null,
        node_id: null,
        task_id: null,
      },
    ],
  },
  AuditEvent: {
    schema: AuditEvent,
    samples: [
      {
        id: "00000000-0000-0000-0000-000000000020",
        tenant_id: "00000000-0000-0000-0000-000000000002",
        action: "REGISTRATION_APPROVED",
        resource_type: "user",
        resource_id: "00000000-0000-0000-0000-000000000003",
        trace_id: "trc_audit",
        detail: {},
        actor_user_id: null,
        created_at: "2026-07-17T00:00:00Z",
      },
    ],
  },
  OutboxEvent: {
    schema: OutboxEvent,
    samples: [
      {
        id: "00000000-0000-0000-0000-000000000010",
        tenant_id: "00000000-0000-0000-0000-000000000002",
        event_type: "MASTERY_DECIDED",
        event_id: "evt_ob_1",
        aggregate_type: "mastery",
        aggregate_id: "agg_1",
        trace_id: "trc_ob",
        payload: {},
        published: false,
        created_at: "2026-07-17T00:00:00Z",
      },
    ],
  },
  IdempotencyRecord: {
    schema: IdempotencyRecord,
    samples: [
      {
        key: "idem_1",
        tenant_id: "00000000-0000-0000-0000-000000000002",
        endpoint: "/api/v1/tasks/123/submit",
        response_status: null,
        response_body: null,
      },
    ],
  },
  ProfileSnapshot: {
    schema: ProfileSnapshot,
    samples: [
      {
        student_id: "00000000-0000-0000-0000-000000000030",
        version: 2,
        source_event_id: "evt_profile_2",
        dimensions: [
          {
            dimension: "DEBUGGING",
            scope_key: "loops",
            score: 0.65,
            confidence: 0.9,
            support_level: 1,
          },
        ],
      },
    ],
  },
  ProfileDisputeRequest: {
    schema: ProfileDisputeRequest,
    samples: [
      {
        profile_version_id: "00000000-0000-0000-0000-000000000031",
        reason: "The debugging score misses my latest attempt.",
      },
    ],
  },
  ProfileDisputeView: {
    schema: ProfileDisputeView,
    samples: [
      {
        id: "00000000-0000-0000-0000-000000000041",
        profile_version_id: "00000000-0000-0000-0000-000000000031",
        reason: "The debugging score misses my latest attempt.",
      },
    ],
  },
  PathSnapshot: {
    schema: PathSnapshot,
    samples: [
      {
        id: "00000000-0000-0000-0000-000000000032",
        course_id: "00000000-0000-0000-0000-000000000033",
        version: 3,
        status: "CURRENT",
        steps: [
          {
            id: "00000000-0000-0000-0000-000000000034",
            position: 1,
            node_id: "00000000-0000-0000-0000-000000000035",
            kind: "LEARN",
            estimated_minutes: 20,
            scenario_key: "loops-v1",
            validation_status: "VALIDATED",
          },
        ],
      },
    ],
  },
  TodayItem: {
    schema: TodayItem,
    samples: [
      {
        id: "00000000-0000-0000-0000-000000000036",
        course_id: "00000000-0000-0000-0000-000000000033",
        node_id: "00000000-0000-0000-0000-000000000035",
        kind: "REVIEW",
        estimated_minutes: 15,
        due_at: "2026-07-24T00:00:00Z",
        task_version_id: null,
      },
    ],
  },
  TaskStartResponse: {
    schema: TaskStartResponse,
    samples: [
      {
        id: "00000000-0000-0000-0000-000000000037",
        task_version_id: "00000000-0000-0000-0000-000000000038",
        status: "ACTIVE",
        snapshot: { prompt: "Fix the loop boundary" },
        started_at: "2026-07-17T00:00:00Z",
        version: 1,
      },
    ],
  },
  AssessmentSubmission: {
    schema: AssessmentSubmission,
    samples: [{ evidence_event_id: "evt_assessment_1", expected_task_version: 1 }],
  },
  TaskSubmissionResponse: {
    schema: TaskSubmissionResponse,
    samples: [
      {
        assessment_id: "00000000-0000-0000-0000-000000000042",
        task_instance_id: "00000000-0000-0000-0000-000000000037",
        course_id: "00000000-0000-0000-0000-000000000033",
        node_id: "00000000-0000-0000-0000-000000000035",
        status: "INITIAL_MASTERY",
        version: 2,
        review_due_at: "2026-07-24T00:00:00Z",
      },
    ],
  },
  MasteryView: {
    schema: MasteryView,
    samples: [
      {
        id: "00000000-0000-0000-0000-000000000039",
        course_id: "00000000-0000-0000-0000-000000000033",
        node_id: "00000000-0000-0000-0000-000000000035",
        status: "INITIAL_MASTERY",
        version: 2,
        review_due_at: "2026-07-24T00:00:00Z",
      },
    ],
  },
  ReviewView: {
    schema: ReviewView,
    samples: [
      {
        id: "00000000-0000-0000-0000-000000000040",
        course_id: "00000000-0000-0000-0000-000000000033",
        node_id: "00000000-0000-0000-0000-000000000035",
        scenario_key: "loops-review-v2",
        due_at: "2026-07-24T00:00:00Z",
        status: "SCHEDULED",
        reschedule_count: 0,
        version: 1,
      },
    ],
  },
  ReviewRescheduleRequest: {
    schema: ReviewRescheduleRequest,
    samples: [{ due_at: "2026-07-25T00:00:00Z", expected_version: 1 }],
  },
};

let failed = 0;

for (const [name, { schema, samples }] of Object.entries(cases)) {
  // Each sample must parse cleanly.
  for (const [i, sample] of samples.entries()) {
    const parsed = (
      schema as { safeParse: (v: unknown) => { success: boolean; error?: { message: string } } }
    ).safeParse(sample);
    if (!parsed.success) {
      console.error(`✗ ${name}[${i}] failed to parse: ${parsed.error?.message}`);
      failed += 1;
    }
  }
}

// The committed JSON Schemas file must exist (exported by export-json-schema.ts).
let schemasRaw: string;
try {
  schemasRaw = readFileSync(SCHEMAS_PATH, "utf8");
} catch {
  console.error(
    `✗ ${SCHEMAS_PATH} missing — run "pnpm contracts:check" which exports schemas first.`,
  );
  failed += 1;
  schemasRaw = "{}";
}

// Sanity: every published model name is present in the committed schemas.
let committed: Record<string, unknown> = {};
try {
  committed = JSON.parse(schemasRaw) as Record<string, unknown>;
} catch (e) {
  console.error("✗ schemas.json is not valid JSON");
  failed += 1;
}
for (const name of Object.keys(cases)) {
  if (!(name in committed)) {
    console.error(`✗ schemas.json missing model: ${name}`);
    failed += 1;
  }
}

if (failed > 0) {
  console.error(`\n${failed} conformance failure(s).`);
  process.exit(1);
}
console.log(`conformance OK: ${Object.keys(cases).length} models, fixtures parsed.`);
