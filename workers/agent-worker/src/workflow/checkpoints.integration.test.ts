import type { AgentAuditEnvelope, AgentNodeName, WorkerJobEnvelope } from "@pymentor/contracts";
import { afterEach, describe, expect, it } from "vitest";

import { buildAgentGraph } from "./graph.js";
import {
  createCheckpointSaver,
  getCheckpointHistory,
  threadIdForJob,
  type CheckpointSaverRuntime,
} from "./checkpoints.js";
import { replayFromCheckpoint } from "./replay.js";

const redisUrl = process.env.PYMENTOR_REDIS_URL;
const describeRedis = redisUrl === undefined ? describe.skip : describe;

describeRedis("RedisSaver checkpoint replay", () => {
  let saverRuntime: CheckpointSaverRuntime | undefined;
  const cleanupThreads: string[] = [];

  afterEach(async () => {
    if (saverRuntime !== undefined) {
      for (const threadId of cleanupThreads.splice(0)) {
        await saverRuntime.saver.deleteThread(threadId);
      }
      await saverRuntime.close();
      saverRuntime = undefined;
    }
  });

  it("stores every super-step and replays only the selected specialist on a new thread", async () => {
    saverRuntime = await createCheckpointSaver(redisUrl!);
    const suffix = Date.now().toString(36);
    const originalEventId = `event-original-${suffix}`;
    const replayEventId = `event-replay-${suffix}`;
    const job: WorkerJobEnvelope = {
      schema_version: 1,
      event_id: originalEventId,
      trace_id: `trace-${suffix}`,
      tenant_id: "tenant-1",
      student_id: "student-1",
      kind: "coding_coach",
      payload: {
        request: "Help with a loop boundary.",
        agent_input: {
          error_summary: "The final element is skipped.",
          test_summary: "The length-one boundary test fails.",
          hint_level: 1,
          context: { evidence_event_ids: ["evidence-1"] },
        },
      },
      enqueued_at: "2026-07-17T12:00:00.000Z",
    };
    const executed: AgentNodeName[] = [];
    const runtime = buildAgentGraph({
      checkpointer: saverRuntime.saver,
      provider: {
        async complete(request) {
          executed.push(request.node);
          if (request.node === "orchestrator") {
            return {
              route: "coach",
              intent_code: "ROUTE_REQUEST",
              summary: "Route coding help to the coach.",
            };
          }
          return {
            kind: "coaching_feedback",
            diagnosis: "The loop bound excludes the final index.",
            hints: ["Compare the final index with the condition."],
            next_test: "Test lengths zero and one.",
          };
        },
      },
      audit: { record: () => undefined },
      now: () => new Date("2026-07-17T12:01:00.000Z"),
    });
    const originalThread = threadIdForJob(job.tenant_id, job.event_id);
    const replayThread = threadIdForJob(job.tenant_id, replayEventId);
    cleanupThreads.push(originalThread, replayThread);

    await runtime.invoke(job, {
      threadId: originalThread,
      agentRunId: originalThread,
    });
    expect(executed).toEqual(["orchestrator", "coach"]);

    const originalHistory = await getCheckpointHistory(saverRuntime.saver, originalThread);
    expect(originalHistory.length).toBeGreaterThanOrEqual(3);
    const beforeSpecialist = originalHistory.find((tuple) => {
      const values = tuple.checkpoint.channel_values;
      return (
        JSON.stringify(values.executedNodes) === JSON.stringify(["orchestrator"]) &&
        values.proposal == null
      );
    });
    expect(beforeSpecialist).toBeDefined();

    executed.length = 0;
    const replayAudit: AgentAuditEnvelope[] = [];
    const replay = await replayFromCheckpoint(
      runtime,
      saverRuntime.saver,
      {
        schema_version: 1,
        tenant_id: job.tenant_id,
        original_event_id: originalEventId,
        replay_event_id: replayEventId,
        checkpoint_id: beforeSpecialist!.checkpoint.id,
        requested_at: "2026-07-17T12:02:00.000Z",
      },
      {
        now: () => new Date("2026-07-17T12:02:00.000Z"),
        publishAudit: async (event) => {
          replayAudit.push(event);
        },
      },
    );

    expect(executed).toEqual(["coach"]);
    expect(replay.executedNodes).toEqual(["orchestrator", "coach"]);
    expect(replay.envelope.event_id).toBe(replayEventId);
    expect(replay.envelope.agent_run_id).toBe(replayThread);
    expect(replayAudit).toHaveLength(1);
    expect(replayAudit[0]).toMatchObject({
      event_type: "REPLAY_STARTED",
      event_id: replayEventId,
      checkpoint_id: beforeSpecialist!.checkpoint.id,
    });

    const originalHistoryAfterReplay = await getCheckpointHistory(
      saverRuntime.saver,
      originalThread,
    );
    expect(originalHistoryAfterReplay).toHaveLength(originalHistory.length);
  });

  it("derives safe fixed-length thread IDs from unsafe external text", () => {
    expect(threadIdForJob("tenant*?[\\]", "event*?[\\]")).toMatch(/^[a-f0-9]{64}$/);
  });
});
