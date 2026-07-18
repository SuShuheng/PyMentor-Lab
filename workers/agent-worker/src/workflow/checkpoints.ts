import { createHash } from "node:crypto";

import type { CheckpointTuple } from "@langchain/langgraph";
import { RedisSaver } from "@langchain/langgraph-checkpoint-redis";

export interface CheckpointSaverRuntime {
  readonly saver: RedisSaver;
  close(): Promise<void>;
}

export async function createCheckpointSaver(redisUrl: string): Promise<CheckpointSaverRuntime> {
  const parsedUrl = new URL(redisUrl);
  if (!new Set(["redis:", "rediss:"]).has(parsedUrl.protocol)) {
    throw new Error("Checkpoint Redis URL must use redis:// or rediss://.");
  }
  const saver = await RedisSaver.fromUrl(parsedUrl.toString());
  return {
    saver,
    close: () => saver.end(),
  };
}

export function threadIdForJob(tenantId: string, eventId: string): string {
  return createHash("sha256").update(`${tenantId}|${eventId}`).digest("hex");
}

export async function getCheckpointHistory(
  saver: RedisSaver,
  threadId: string,
  limit = 100,
): Promise<CheckpointTuple[]> {
  const history: CheckpointTuple[] = [];
  for await (const tuple of saver.list({ configurable: { thread_id: threadId } }, { limit })) {
    history.push(tuple);
  }
  return history;
}
