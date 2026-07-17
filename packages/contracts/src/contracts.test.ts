import { describe, expect, it } from "vitest";

import {
  ChatCompletionChunk,
  ErrorEnvelope,
  ErrorCode,
  HealthResponse,
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
      { type: "content_delta", event_id: "e1", chunk: { id: "c1", chunk_index: 0, delta_content: "x", timestamp: "t" } },
      { type: "reasoning_delta", event_id: "e2", chunk: { id: "c1", chunk_index: 1, delta_reasoning: "y", timestamp: "t" } },
      { type: "tool_call_delta", event_id: "e3", chunk: { id: "c1", chunk_index: 2, delta_tool_calls: [{ index: 0 }], timestamp: "t" } },
      { type: "progress", event_id: "e4", percent: 10 },
      { type: "error", event_id: "e5", error: { code: "TIMEOUT", message: "slow", trace_id: "t1", retryable: true } },
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
      duration_ms: 0,
      peak_memory_kb: null,
      user_error: null,
      platform_error: "runner crashed",
    });
    expect(parsed.success).toBe(true);
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
