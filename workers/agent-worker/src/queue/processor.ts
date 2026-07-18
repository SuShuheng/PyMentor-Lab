import {
  AgentAuditEnvelope,
  AgentProposalEnvelope,
  WorkerJobEnvelope,
  type AgentAuditDetail,
  type AgentAuditEnvelope as AgentAuditEnvelopeValue,
  type AgentAuditEventType,
  type AgentProposalEnvelope as AgentProposalEnvelopeValue,
  type WorkerJobEnvelope as WorkerJobEnvelopeValue,
  type WorkerJobStatus,
} from "@pymentor/contracts";

import type { AgentAuditRecord, AgentAuditSink } from "../agents/types.js";
import type { AgentGraphInvokeOptions, AgentGraphResult } from "../workflow/graph.js";
import { publishAgentEvent, type RedisStreamPort } from "./events.js";
import { jobIdForEvent } from "./identities.js";

const RUN_KEY_PREFIX = "pymentor:agent-run:v1:";
const COMPLETION_KEY_PREFIX = "pymentor:agent-completed:v1:";
const SEQUENCE_KEY_PREFIX = "pymentor:agent-sequence:v1:";
const RUN_CLAIM_TTL_MS = 15 * 60 * 1_000;

export interface RedisRunStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, options?: { nx?: boolean; ttlMs?: number }): Promise<boolean>;
  nextSequence(key: string): Promise<number>;
}

export interface AgentCompletionStore {
  commit(
    completionKey: string,
    completionValue: string,
    events: readonly (AgentAuditEnvelopeValue | AgentProposalEnvelopeValue)[],
  ): Promise<void>;
}

export interface ProcessorGraphResult extends AgentGraphResult {
  readonly checkpointId?: string;
}

export interface ProcessorGraphRuntime {
  invoke(
    job: WorkerJobEnvelopeValue,
    options: AgentGraphInvokeOptions,
  ): Promise<ProcessorGraphResult>;
  resume(options: AgentGraphInvokeOptions): Promise<ProcessorGraphResult>;
  hasCheckpoint(options: AgentGraphInvokeOptions): Promise<boolean>;
}

export interface AgentProcessorDependencies {
  readonly store: RedisRunStore;
  readonly stream: RedisStreamPort;
  readonly graphFactory: (audit: AgentAuditSink) => ProcessorGraphRuntime;
  readonly completion: AgentCompletionStore;
  readonly now?: () => Date;
}

export interface AgentJobAttempt {
  readonly attempt: number;
}

export class AgentJobProcessingError extends Error {
  constructor(
    readonly code: string,
    readonly retryable: boolean,
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "AgentJobProcessingError";
  }
}

class SequentialAudit implements AgentAuditSink {
  constructor(
    private readonly job: WorkerJobEnvelopeValue,
    private readonly agentRunId: string,
    private readonly stream: RedisStreamPort,
    private readonly store: RedisRunStore,
    private readonly sequenceKey: string,
    private readonly now: () => Date,
  ) {}

  async envelope(
    eventType: AgentAuditEventType,
    detail: AgentAuditDetail,
    extra: {
      node?: AgentAuditEnvelopeValue["node"];
      toolName?: string;
      checkpointId?: string;
    } = {},
  ): Promise<AgentAuditEnvelopeValue> {
    const sequence = await this.store.nextSequence(this.sequenceKey);
    return AgentAuditEnvelope.parse({
      schema_version: 1,
      agent_run_id: this.agentRunId,
      event_id: this.job.event_id,
      trace_id: this.job.trace_id,
      tenant_id: this.job.tenant_id,
      student_id: this.job.student_id,
      sequence,
      event_type: eventType,
      ...(extra.node === undefined ? {} : { node: extra.node }),
      ...(extra.toolName === undefined ? {} : { tool_name: extra.toolName }),
      ...(extra.checkpointId === undefined ? {} : { checkpoint_id: extra.checkpointId }),
      detail,
      occurred_at: this.now().toISOString(),
    });
  }

  async publish(
    eventType: AgentAuditEventType,
    detail: AgentAuditDetail,
    extra: {
      node?: AgentAuditEnvelopeValue["node"];
      toolName?: string;
      checkpointId?: string;
    } = {},
  ): Promise<void> {
    await publishAgentEvent(this.stream, await this.envelope(eventType, detail, extra));
  }

  async record(record: AgentAuditRecord): Promise<void> {
    if (record.eventId !== this.job.event_id) {
      throw new AgentJobProcessingError(
        "AUDIT_IDENTITY_MISMATCH",
        false,
        "Node audit event identity did not match the active job.",
      );
    }
    await this.publish(record.eventType, record.detail, {
      node: record.node,
      ...(record.toolName === undefined ? {} : { toolName: record.toolName }),
    });
  }
}

function validationError(error: unknown): AgentJobProcessingError {
  return new AgentJobProcessingError(
    "VALIDATION_ERROR",
    false,
    "Worker job envelope did not match schema version 1.",
    { cause: error },
  );
}

const FINAL_ERROR_CODES = new Set([
  "AUDIT_IDENTITY_MISMATCH",
  "FORBIDDEN_TOOL",
  "INVALID_FALLBACK",
  "INVALID_INPUT",
  "INVALID_TOOL_INPUT",
  "INVALID_TOOL_OUTPUT",
  "INVALID_WORKFLOW_PAYLOAD",
  "ROUTE_MISMATCH",
  "VALIDATION_ERROR",
]);

function classifyError(error: unknown): AgentJobProcessingError {
  if (error instanceof AgentJobProcessingError) {
    return error;
  }
  const rawCode =
    typeof error === "object" && error !== null && "code" in error
      ? String(error.code)
      : "UNEXPECTED_ERROR";
  const code = /^[A-Z][A-Z0-9_]{0,63}$/.test(rawCode) ? rawCode : "UNEXPECTED_ERROR";
  return new AgentJobProcessingError(
    code,
    !FINAL_ERROR_CODES.has(code),
    "Agent job processing failed.",
    { cause: error },
  );
}

function assertProposalIdentity(
  envelope: AgentProposalEnvelopeValue,
  job: WorkerJobEnvelopeValue,
  runId: string,
): void {
  if (
    envelope.agent_run_id !== runId ||
    envelope.event_id !== job.event_id ||
    envelope.trace_id !== job.trace_id ||
    envelope.tenant_id !== job.tenant_id ||
    envelope.student_id !== job.student_id
  ) {
    throw new AgentJobProcessingError(
      "PROPOSAL_IDENTITY_MISMATCH",
      false,
      "Graph proposal identity did not match the active job.",
    );
  }
}

export async function processAgentJob(
  rawJob: unknown,
  attempt: AgentJobAttempt,
  dependencies: AgentProcessorDependencies,
): Promise<AgentProposalEnvelopeValue> {
  const parsed = WorkerJobEnvelope.safeParse(rawJob);
  if (!parsed.success) {
    throw validationError(parsed.error);
  }
  const job = parsed.data;
  const runId = jobIdForEvent(job);
  const completionKey = `${COMPLETION_KEY_PREFIX}${runId}`;
  const runKey = `${RUN_KEY_PREFIX}${runId}`;
  const sequenceKey = `${SEQUENCE_KEY_PREFIX}${runId}`;
  const cached = await dependencies.store.get(completionKey);
  if (cached !== null) {
    return AgentProposalEnvelope.parse(JSON.parse(cached));
  }

  const claimed = await dependencies.store.set(
    runKey,
    JSON.stringify({ thread_id: runId, status: "RUNNING" }),
    { nx: true, ttlMs: RUN_CLAIM_TTL_MS },
  );
  if (!claimed && attempt.attempt === 0) {
    throw new AgentJobProcessingError(
      "RUN_ACTIVE",
      true,
      "An active delivery already owns this run identity.",
    );
  }

  const now = dependencies.now ?? (() => new Date());
  const audit = new SequentialAudit(
    job,
    runId,
    dependencies.stream,
    dependencies.store,
    sequenceKey,
    now,
  );
  await audit.publish("RUN_STARTED", {
    status: "RUNNING",
    retry_count: Math.min(10, Math.max(0, attempt.attempt)),
  });

  try {
    const graph = dependencies.graphFactory(audit);
    const graphOptions = { threadId: runId, agentRunId: runId };
    const hasCheckpoint =
      attempt.attempt > 0 ? await graph.hasCheckpoint(graphOptions) : false;
    const result = hasCheckpoint
      ? await (async () => {
            await audit.publish("REPLAY_STARTED", {
              status: "RUNNING",
              retry_count: Math.min(10, Math.max(0, attempt.attempt)),
            });
            return graph.resume(graphOptions);
          })()
      : await graph.invoke(job, graphOptions);
    const envelope = AgentProposalEnvelope.parse(result.envelope);
    assertProposalIdentity(envelope, job, runId);
    if (result.checkpointId !== undefined) {
      await audit.publish(
        "CHECKPOINT_SAVED",
        { status: "RUNNING" },
        { checkpointId: result.checkpointId },
      );
    }
    const completed = await audit.envelope("RUN_COMPLETED", {
      status: "SUCCEEDED",
      fallback: envelope.fallback_used,
    });
    await dependencies.completion.commit(completionKey, JSON.stringify(envelope), [
      envelope,
      completed,
    ]);
    return envelope;
  } catch (error) {
    const classified = classifyError(error);
    const status: WorkerJobStatus = classified.retryable ? "FAILED_RETRYABLE" : "FAILED_FINAL";
    await audit.publish("RUN_FAILED", {
      status,
      code: classified.code,
      retry_count: Math.min(10, Math.max(0, attempt.attempt)),
    });
    throw classified;
  }
}
