import type { RedisSaver } from "@langchain/langgraph-checkpoint-redis";
import {
  AgentAuditEnvelope,
  AgentReplayRequest,
  SpecialistAgentNodeName,
  WorkerJobEnvelope,
  type AgentAuditEnvelope as AgentAuditEnvelopeValue,
} from "@pymentor/contracts";
import { z } from "zod";

import { getCheckpointHistory, threadIdForJob } from "./checkpoints.js";
import type { AgentGraphResult, AgentGraphRuntime } from "./graph.js";

const ReplayableState = z
  .object({
    job: WorkerJobEnvelope,
    route: SpecialistAgentNodeName,
    executedNodes: z.tuple([z.literal("orchestrator")]),
    proposal: z.null().optional(),
    auditSequence: z.number().int().nonnegative(),
    fallbackUsed: z.boolean(),
    terminalFailure: z.null().optional(),
  })
  .passthrough();

export interface ReplayOptions {
  readonly now?: () => Date;
  readonly publishAudit?: (event: AgentAuditEnvelopeValue) => Promise<void>;
}

export async function replayFromCheckpoint(
  runtime: AgentGraphRuntime,
  saver: RedisSaver,
  rawRequest: unknown,
  options: ReplayOptions = {},
): Promise<AgentGraphResult> {
  const request = AgentReplayRequest.parse(rawRequest);
  const originalThread = threadIdForJob(request.tenant_id, request.original_event_id);
  const replayThread = threadIdForJob(request.tenant_id, request.replay_event_id);
  const history = await getCheckpointHistory(saver, originalThread);
  const selected = history.find(({ checkpoint }) => checkpoint.id === request.checkpoint_id);
  if (selected === undefined) {
    throw new Error("Requested checkpoint does not belong to the original run.");
  }
  const selectedState = ReplayableState.parse(selected.checkpoint.channel_values);
  if (
    selectedState.job.tenant_id !== request.tenant_id ||
    selectedState.job.event_id !== request.original_event_id
  ) {
    throw new Error("Checkpoint job identity did not match the replay request.");
  }

  const replayJob = WorkerJobEnvelope.parse({
    ...selectedState.job,
    event_id: request.replay_event_id,
    enqueued_at: request.requested_at,
  });
  await runtime.compiled.updateState(
    { configurable: { thread_id: replayThread } },
    {
      ...selectedState,
      job: replayJob,
      proposal: null,
      auditSequence: 0,
      terminalFailure: null,
    },
    "orchestrator",
  );

  const now = options.now ?? (() => new Date());
  const audit = AgentAuditEnvelope.parse({
    schema_version: 1,
    agent_run_id: replayThread,
    event_id: request.replay_event_id,
    trace_id: replayJob.trace_id,
    tenant_id: replayJob.tenant_id,
    student_id: replayJob.student_id,
    sequence: 1,
    event_type: "REPLAY_STARTED",
    checkpoint_id: request.checkpoint_id,
    detail: { status: "RUNNING", code: "REPLAY_FROM_CHECKPOINT" },
    occurred_at: now().toISOString(),
  });
  await options.publishAudit?.(audit);

  return runtime.resume({
    threadId: replayThread,
    agentRunId: replayThread,
  });
}
