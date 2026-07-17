import { createHash } from "node:crypto";

import {
  AgentAuditEnvelope,
  AgentProposalEnvelope,
  type AgentProposalEnvelope as AgentProposalEnvelopeValue,
  type WorkerJobEnvelope,
} from "@pymentor/contracts";
import { describe, expect, it, vi } from "vitest";

import { jobIdForEvent, toolIdempotencyKey } from "./identities.js";
import {
  AGENT_EVENT_STREAM,
  AGENT_EVENT_STREAM_MAXLEN,
  publishAgentEvent,
  type RedisStreamPort,
} from "./events.js";
import {
  AgentJobProcessingError,
  processAgentJob,
  type AgentProcessorDependencies,
  type RedisRunStore,
} from "./processor.js";
import {
  AGENT_QUEUE_DEFAULT_JOB_OPTIONS,
  AGENT_QUEUE_NAME,
  AGENT_QUEUE_PREFIX,
} from "./runtime.js";

const job: WorkerJobEnvelope = {
  schema_version: 1,
  event_id: "event-1",
  trace_id: "trace-1",
  tenant_id: "tenant-1",
  student_id: "student-1",
  kind: "coding_coach",
  payload: {
    request: "Help with this loop boundary.",
    agent_input: {
      error_summary: "The final element is skipped.",
      test_summary: "The length-one boundary test fails.",
      hint_level: 1,
      context: { evidence_event_ids: ["evidence-1"] },
    },
  },
  enqueued_at: "2026-07-17T12:00:00.000Z",
};

function proposalEnvelope(
  overrides: Partial<AgentProposalEnvelopeValue> = {},
): AgentProposalEnvelopeValue {
  return AgentProposalEnvelope.parse({
    schema_version: 1,
    agent_run_id: jobIdForEvent(job),
    event_id: job.event_id,
    trace_id: job.trace_id,
    tenant_id: job.tenant_id,
    student_id: job.student_id,
    node: "coach",
    status: "SUCCEEDED",
    proposal: {
      kind: "coaching_feedback",
      diagnosis: "The loop bound excludes the final index.",
      hints: ["Compare the final index with the condition."],
      next_test: "Test lengths zero and one.",
    },
    fallback_used: false,
    completed_at: "2026-07-17T12:01:00.000Z",
    ...overrides,
  });
}

class MemoryRunStore implements RedisRunStore {
  readonly values = new Map<string, string>();
  readonly calls: string[] = [];

  async get(key: string): Promise<string | null> {
    this.calls.push(`get:${key}`);
    return this.values.get(key) ?? null;
  }

  async set(
    key: string,
    value: string,
    options: { nx?: boolean; ttlMs?: number } = {},
  ): Promise<boolean> {
    this.calls.push(`set:${key}:${options.nx === true ? "nx" : "plain"}`);
    if (options.nx === true && this.values.has(key)) {
      return false;
    }
    this.values.set(key, value);
    return true;
  }
}

class MemoryStream implements RedisStreamPort {
  readonly calls: Array<{ stream: string; args: Array<string | number> }> = [];

  async xadd(stream: string, ...args: Array<string | number>): Promise<string> {
    this.calls.push({ stream, args });
    return `${this.calls.length}-0`;
  }

  payloads(): unknown[] {
    return this.calls.map(({ args }) => {
      const payloadIndex = args.indexOf("payload");
      return JSON.parse(String(args[payloadIndex + 1]));
    });
  }
}

function dependencies(
  store: MemoryRunStore,
  stream: MemoryStream,
  invoke = vi.fn().mockResolvedValue({
    envelope: proposalEnvelope(),
    executedNodes: ["orchestrator", "coach"],
    auditSequence: 4,
    checkpointId: "checkpoint-1",
  }),
): AgentProcessorDependencies {
  return {
    store,
    stream,
    graphFactory: (audit) => ({
      invoke: async (inputJob, options) => {
        await audit.record({
          eventType: "NODE_STARTED",
          eventId: inputJob.event_id,
          node: "orchestrator",
          status: "RUNNING",
          detail: { status: "RUNNING" },
        });
        await audit.record({
          eventType: "NODE_COMPLETED",
          eventId: inputJob.event_id,
          node: "orchestrator",
          status: "SUCCEEDED",
          detail: { status: "SUCCEEDED", fallback: false },
        });
        return invoke(inputJob, options);
      },
    }),
    now: () => new Date("2026-07-17T12:01:00.000Z"),
  };
}

describe("agent queue processor", () => {
  it("pins bounded BullMQ retry and retention policy", () => {
    expect(AGENT_QUEUE_NAME).not.toContain(":");
    expect(`${AGENT_QUEUE_PREFIX}:${AGENT_QUEUE_NAME}`).toBe("pymentor:agent-jobs:v1");
    expect(AGENT_QUEUE_DEFAULT_JOB_OPTIONS).toMatchObject({
      attempts: 3,
      backoff: { type: "exponential", delay: 1_000 },
      removeOnComplete: { count: 1_000 },
      removeOnFail: { count: 5_000 },
    });
  });

  it("derives fixed SHA-256 identities without unsafe event text", () => {
    expect(jobIdForEvent(job)).toBe(
      createHash("sha256").update(`${job.tenant_id}|${job.event_id}`).digest("hex"),
    );
    expect(jobIdForEvent({ ...job, event_id: "unsafe*?[\\]" })).toMatch(/^[a-f0-9]{64}$/);
    expect(toolIdempotencyKey("event-1", "path", "knowledge.search", 3)).toBe(
      createHash("sha256").update("event-1|path|knowledge.search|3").digest("hex"),
    );
  });

  it("rejects an invalid envelope before Redis or graph access", async () => {
    const store = new MemoryRunStore();
    const stream = new MemoryStream();
    const invoke = vi.fn();

    await expect(
      processAgentJob(
        { event_id: "unsafe event" },
        { attempt: 0 },
        dependencies(store, stream, invoke),
      ),
    ).rejects.toMatchObject({ code: "VALIDATION_ERROR", retryable: false });

    expect(store.calls).toEqual([]);
    expect(stream.calls).toEqual([]);
    expect(invoke).not.toHaveBeenCalled();
  });

  it("returns a validated completed duplicate without rerunning the graph", async () => {
    const store = new MemoryRunStore();
    const stream = new MemoryStream();
    const invoke = vi.fn().mockResolvedValue({
      envelope: proposalEnvelope(),
      executedNodes: ["orchestrator", "coach"],
      auditSequence: 4,
      checkpointId: "checkpoint-1",
    });
    const deps = dependencies(store, stream, invoke);

    const first = await processAgentJob(job, { attempt: 0 }, deps);
    const second = await processAgentJob(job, { attempt: 0 }, deps);

    expect(first).toEqual(proposalEnvelope());
    expect(second).toEqual(first);
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it("resumes an interrupted retry with the same digest thread identity", async () => {
    const store = new MemoryRunStore();
    const stream = new MemoryStream();
    const runId = jobIdForEvent(job);
    store.values.set(
      `pymentor:agent-run:v1:${runId}`,
      JSON.stringify({ thread_id: runId, status: "RUNNING" }),
    );
    const invoke = vi.fn().mockResolvedValue({
      envelope: proposalEnvelope(),
      executedNodes: ["orchestrator", "coach"],
      auditSequence: 4,
      checkpointId: "checkpoint-1",
    });

    await processAgentJob(job, { attempt: 1 }, dependencies(store, stream, invoke));

    expect(invoke).toHaveBeenCalledWith(
      job,
      expect.objectContaining({ threadId: runId, agentRunId: runId }),
    );
  });

  it.each([
    [true, "PROVIDER_UNAVAILABLE", "FAILED_RETRYABLE"],
    [false, "FORBIDDEN_TOOL", "FAILED_FINAL"],
  ] as const)("classifies retryable=%s failures as %s", async (retryable, code, status) => {
    const store = new MemoryRunStore();
    const stream = new MemoryStream();
    const error = new AgentJobProcessingError(code, retryable, "safe failure");
    const invoke = vi.fn().mockRejectedValue(error);

    await expect(
      processAgentJob(job, { attempt: 0 }, dependencies(store, stream, invoke)),
    ).rejects.toMatchObject({ code, retryable });

    const audit = stream
      .payloads()
      .map((payload) => AgentAuditEnvelope.safeParse(payload))
      .filter((result) => result.success)
      .map((result) => result.data);
    expect(audit.at(-1)).toMatchObject({
      event_type: "RUN_FAILED",
      detail: { status, code },
    });
  });

  it("publishes monotonic audit events, a checkpoint, and one terminal event", async () => {
    const store = new MemoryRunStore();
    const stream = new MemoryStream();

    await processAgentJob(job, { attempt: 0 }, dependencies(store, stream));

    const audit = stream
      .payloads()
      .map((payload) => AgentAuditEnvelope.safeParse(payload))
      .filter((result) => result.success)
      .map((result) => result.data);
    expect(audit.map(({ sequence }) => sequence)).toEqual([1, 2, 3, 4, 5]);
    expect(audit.map(({ event_type }) => event_type)).toEqual([
      "RUN_STARTED",
      "NODE_STARTED",
      "NODE_COMPLETED",
      "CHECKPOINT_SAVED",
      "RUN_COMPLETED",
    ]);
    expect(audit.filter(({ event_type }) => event_type === "RUN_COMPLETED")).toHaveLength(1);
  });

  it("uses an approximate capped Redis stream write", async () => {
    const stream = new MemoryStream();
    await publishAgentEvent(stream, proposalEnvelope());

    expect(stream.calls[0]).toEqual({
      stream: AGENT_EVENT_STREAM,
      args: [
        "MAXLEN",
        "~",
        AGENT_EVENT_STREAM_MAXLEN,
        "*",
        "payload",
        JSON.stringify(proposalEnvelope()),
      ],
    });
  });
});
