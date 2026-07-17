import { describe, expect, it } from "vitest";

import {
  ChatCompletionChunk,
  CodeRunRequest,
  CodeRunView,
  CodeSubmissionRequest,
  ErrorEnvelope,
  ErrorCode,
  HealthResponse,
  HintRequest,
  HintUsageView,
  SandboxExecutionRequest,
  SandboxExecutionResponse,
  SandboxResult,
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
      status: "PLATFORM_ERROR",
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
      status: "COMPLETED",
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
});
