import { describe, expect, it } from "vitest";

import {
  AgentAuditEnvelope,
  AgentProposalEnvelope,
  AgentReplayRequest,
  AssessmentAgentInput,
  AssessmentAgentOutput,
  ChatCompletionChunk,
  CoachAgentInput,
  CoachAgentOutput,
  CodeRunStatus,
  CodeRunRequest,
  CodeRunView,
  CodeSubmissionRequest,
  ErrorEnvelope,
  ErrorCode,
  HealthResponse,
  HintRequest,
  HintUsageView,
  OrchestratorAgentInput,
  OrchestratorAgentOutput,
  PathAgentInput,
  PathAgentOutput,
  ProfileAgentInput,
  ProfileAgentOutput,
  ResourceAgentInput,
  ResourceAgentOutput,
  SandboxExecutionRequest,
  SandboxExecutionResponse,
  SandboxResult,
  SandboxRunStatus,
  StreamEvent,
  SystemPingResponse,
  WorkerJobEnvelope,
} from "./index.js";

describe("contracts", () => {
  it("exposes all 15 stable error codes", () => {
    const all = ErrorCode.options;
    expect(all).toHaveLength(15);
    expect(all).toContain("IPC_CAPABILITY_DENIED");
  });

  it("parses a valid ErrorEnvelope", () => {
    const parsed = ErrorEnvelope.safeParse({
      code: "VALIDATION_ERROR",
      message: "bad",
      trace_id: "t1",
      retryable: false,
    });
    expect(parsed.success).toBe(true);
  });

  it("parses HealthResponse, SystemPingResponse", () => {
    expect(
      HealthResponse.safeParse({
        status: "ok",
        service: "api",
        version: "0.0.0",
        timestamp: "2026-07-17T00:00:00Z",
      }).success,
    ).toBe(true);
    expect(
      SystemPingResponse.safeParse({
        ok: true,
        service: "api",
        timestamp: "2026-07-17T00:00:00Z",
      }).success,
    ).toBe(true);
  });

  it("parses ChatCompletionChunk with optional reasoning/tool streams", () => {
    expect(
      ChatCompletionChunk.safeParse({
        id: "c1",
        chunk_index: 0,
        delta_content: "x",
        timestamp: "2026-07-17T00:00:00Z",
      }).success,
    ).toBe(true);
  });

  it("parses the full StreamEvent discriminated union", () => {
    for (const ev of [
      {
        type: "content_delta",
        event_id: "e1",
        chunk: { id: "c1", chunk_index: 0, delta_content: "x", timestamp: "t" },
      },
      {
        type: "reasoning_delta",
        event_id: "e2",
        chunk: { id: "c1", chunk_index: 1, delta_reasoning: "y", timestamp: "t" },
      },
      {
        type: "tool_call_delta",
        event_id: "e3",
        chunk: { id: "c1", chunk_index: 2, delta_tool_calls: [{ index: 0 }], timestamp: "t" },
      },
      { type: "progress", event_id: "e4", percent: 10 },
      {
        type: "error",
        event_id: "e5",
        error: { code: "TIMEOUT", message: "slow", trace_id: "t1", retryable: true },
      },
      { type: "done", event_id: "e6" },
    ]) {
      expect(StreamEvent.safeParse(ev).success).toBe(true);
    }
  });

  it("separates sandbox user_error from platform_error", () => {
    const parsed = SandboxResult.safeParse({
      run_id: "r1",
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
    });
    expect(parsed.success).toBe(true);
  });

  it("keeps sandbox outcomes separate from persisted run lifecycle", () => {
    expect(SandboxRunStatus.safeParse("PASSED").success).toBe(true);
    expect(SandboxRunStatus.safeParse("PLATFORM_ERROR").success).toBe(false);
    expect(CodeRunStatus.safeParse("PLATFORM_ERROR").success).toBe(true);
  });

  it("parses code-run, submission, and hint API contracts", () => {
    expect(
      CodeRunRequest.safeParse({
        task_instance_id: "tsk_1",
        source_code: "def solve(value):\n    return value + 1\n",
        mode: "TRACE",
        expected_task_version: 3,
        trace_enabled: true,
      }).success,
    ).toBe(true);
    expect(
      CodeSubmissionRequest.safeParse({
        task_instance_id: "tsk_1",
        source_code: "def solve(value):\n    return value + 1\n",
        expected_task_version: 3,
      }).success,
    ).toBe(true);
    expect(
      CodeRunView.safeParse({
        run_id: "run_1",
        task_instance_id: "tsk_1",
        mode: "RUN",
        status: "QUEUED",
        version: 1,
        revision: {
          id: "rev_1",
          sequence: 1,
          source_digest: "a".repeat(64),
          created_at: "2026-07-17T00:00:00Z",
        },
        requested_at: "2026-07-17T00:00:00Z",
      }).success,
    ).toBe(true);
    expect(HintRequest.safeParse({ level: 1, expected_task_version: 3 }).success).toBe(true);
    expect(
      HintUsageView.safeParse({
        id: "hint_1",
        task_instance_id: "tsk_1",
        sequence: 1,
        hint_key: "loop-bound",
        level: 1,
        cost: 0.1,
        content: "Check the loop boundary.",
        created_at: "2026-07-17T00:00:00Z",
      }).success,
    ).toBe(true);
  });

  it("strictly validates the private sandbox supervisor protocol", () => {
    const request = {
      protocol_version: "1",
      request_id: "req_1",
      run_id: "run_1",
      trace_id: "trc_1",
      source_code: "def solve(value):\n    return value + 1\n",
      entrypoint: { kind: "FUNCTION", name: "solve" },
      cases: [{ id: "basic", args: [1], expected: 2 }],
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
    };
    expect(SandboxExecutionRequest.safeParse(request).success).toBe(true);
    expect(SandboxExecutionRequest.safeParse({ ...request, unexpected: true }).success).toBe(false);

    const result = {
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
    };
    expect(
      SandboxExecutionResponse.safeParse({
        protocol_version: "1",
        request_id: "req_1",
        run_id: "run_1",
        result,
      }).success,
    ).toBe(true);
  });

  it("requires schema_version on WorkerJobEnvelope", () => {
    const ok = WorkerJobEnvelope.safeParse({
      schema_version: 1,
      event_id: "e1",
      trace_id: "t1",
      tenant_id: "tn1",
      student_id: "s1",
      kind: "tutoring_answer",
      payload: {},
      enqueued_at: "2026-07-17T00:00:00Z",
    });
    expect(ok.success).toBe(true);
    const bad = WorkerJobEnvelope.safeParse({ schema_version: 2 });
    expect(bad.success).toBe(false);
  });

  it("parses one strict golden input and output for every Agent node", () => {
    const context = {
      course_id: "course_python_1",
      node_id: "node_loops",
      task_id: "task_loop_boundary",
      evidence_event_ids: ["evt_code_1"],
    };
    const goldens: Array<{ schema: { parse(value: unknown): unknown }; value: unknown }> = [
      {
        schema: OrchestratorAgentInput,
        value: { kind: "coding_coach", request: "Explain the failed loop test.", context },
      },
      {
        schema: OrchestratorAgentOutput,
        value: { route: "coach", intent_code: "CODE_FAILURE", summary: "Coach the failed test." },
      },
      {
        schema: ProfileAgentInput,
        value: { evidence_summary: "Three loop-boundary failures.", current_profile_version: 3, context },
      },
      {
        schema: ProfileAgentOutput,
        value: {
          kind: "profile_change",
          changes: [{ dimension: "DEBUGGING", delta: -0.1, reason: "Repeated boundary misses." }],
        },
      },
      {
        schema: PathAgentInput,
        value: {
          profile_summary: "Needs loop-boundary remediation.",
          available_minutes: 30,
          candidate_node_ids: ["node_loops", "node_ranges"],
          context,
        },
      },
      {
        schema: PathAgentOutput,
        value: {
          kind: "path_plan",
          steps: [{ node_id: "node_ranges", action: "REMEDIATE", reason: "Repair range semantics." }],
        },
      },
      {
        schema: ResourceAgentInput,
        value: {
          learning_need: "Understand exclusive range bounds.",
          resource_types: ["MICRO_LECTURE", "STRUCTURE_CARD"],
          tutoring_question: "Why is the last item missing?",
          context,
        },
      },
      {
        schema: ResourceAgentOutput,
        value: {
          kind: "resource_request",
          requests: [
            {
              resource_type: "MICRO_LECTURE",
              objective: "Contrast inclusive and exclusive bounds.",
            },
          ],
          answer: "Python range excludes its stop value.",
        },
      },
      {
        schema: CoachAgentInput,
        value: {
          error_summary: "Expected 4 values, received 3.",
          test_summary: "Hidden upper-bound case failed.",
          hint_level: 1,
          context,
        },
      },
      {
        schema: CoachAgentOutput,
        value: {
          kind: "coaching_feedback",
          diagnosis: "The loop stops one step early.",
          hints: ["Inspect the stop argument."],
          next_test: "Try the smallest non-empty boundary.",
        },
      },
      {
        schema: AssessmentAgentInput,
        value: {
          response_summary: "Student explains the exclusive stop value.",
          rubric_keys: ["CONCEPT", "TRANSFER"],
          context,
        },
      },
      {
        schema: AssessmentAgentOutput,
        value: {
          kind: "assessment_feedback",
          rubric_scores: { CONCEPT: 0.9, TRANSFER: 0.7 },
          feedback: "Correct explanation with partial transfer.",
          evidence_claims: ["Explains exclusive bounds."],
        },
      },
    ];

    for (const { schema, value } of goldens) {
      expect(schema.parse(value)).toEqual(value);
      expect(() => schema.parse({ ...(value as object), unexpected: true })).toThrow();
    }
  });

  it("strictly validates proposal, audit, and replay envelopes", () => {
    const proposal = {
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
    };
    expect(AgentProposalEnvelope.parse(proposal)).toEqual(proposal);
    expect(() =>
      AgentProposalEnvelope.parse({ ...proposal, node: "profile" }),
    ).toThrow(/proposal kind/);
    expect(() =>
      AgentProposalEnvelope.parse({ ...proposal, error_code: "UNEXPECTED_ERROR" }),
    ).toThrow(/cannot include an error code/);
    expect(() =>
      AgentProposalEnvelope.parse({
        ...proposal,
        status: "FAILED_FINAL",
        error_code: "UNEXPECTED_ERROR",
      }),
    ).toThrow(/cannot include a proposal/);

    const audit = {
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
    };
    expect(AgentAuditEnvelope.parse(audit)).toEqual(audit);
    expect(() =>
      AgentAuditEnvelope.parse({ ...audit, detail: { raw_prompt: "secret system prompt" } }),
    ).toThrow();

    const replay = {
      schema_version: 1,
      tenant_id: "tnt_demo",
      original_event_id: "evt_job_1",
      replay_event_id: "evt_job_1_replay_1",
      checkpoint_id: "chk_1",
      requested_at: "2026-07-17T00:00:00Z",
    };
    expect(AgentReplayRequest.parse(replay)).toEqual(replay);
    expect(() =>
      AgentReplayRequest.parse({ ...replay, replay_event_id: replay.original_event_id }),
    ).toThrow();
  });

  it("bounds Worker identities and requires real UTC timestamps", () => {
    const base = {
      schema_version: 1,
      event_id: "evt_job_1",
      trace_id: "trc_1",
      tenant_id: "tnt_demo",
      student_id: "stu_1",
      kind: "resource_generate",
      payload: { need: "loops" },
      enqueued_at: "2026-07-17T00:00:00Z",
    };
    expect(() => WorkerJobEnvelope.parse({ ...base, event_id: "x".repeat(129) })).toThrow();
    expect(() => WorkerJobEnvelope.parse({ ...base, event_id: "unsafe*event" })).toThrow();
    expect(() => WorkerJobEnvelope.parse({ ...base, enqueued_at: "soon" })).toThrow();
    expect(() => WorkerJobEnvelope.parse({ ...base, enqueued_at: "2026-07-18T01:02:03" })).toThrow();
    expect(() => WorkerJobEnvelope.parse({ ...base, unexpected: true })).toThrow();
  });
});
