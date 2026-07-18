import { createHash } from "node:crypto";

import type { AgentNodeName, WorkerJobEnvelope } from "@pymentor/contracts";

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

export function jobIdForEvent(job: Pick<WorkerJobEnvelope, "tenant_id" | "event_id">): string {
  return sha256(`${job.tenant_id}|${job.event_id}`);
}

export function toolIdempotencyKey(
  eventId: string,
  node: AgentNodeName,
  toolName: string,
  sequence: number,
): string {
  return sha256(`${eventId}|${node}|${toolName}|${sequence}`);
}
