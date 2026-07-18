import {
  AgentAuditEnvelope,
  AgentProposalEnvelope,
  type AgentAuditEnvelope as AgentAuditEnvelopeValue,
  type AgentProposalEnvelope as AgentProposalEnvelopeValue,
} from "@pymentor/contracts";

export const AGENT_EVENT_STREAM = "pymentor:agent-events:v1";
export const AGENT_EVENT_STREAM_MAXLEN = 10_000;

export interface RedisStreamPort {
  xadd(stream: string, ...args: Array<string | number>): Promise<string | null>;
}

export type AgentEventEnvelope = AgentAuditEnvelopeValue | AgentProposalEnvelopeValue;

export function validateAgentEvent(event: unknown): AgentEventEnvelope {
  const audit = AgentAuditEnvelope.safeParse(event);
  if (audit.success) {
    return audit.data;
  }
  return AgentProposalEnvelope.parse(event);
}

export function serializeAgentEvent(event: unknown): string {
  return JSON.stringify(validateAgentEvent(event));
}

export async function publishAgentEvent(redis: RedisStreamPort, event: unknown): Promise<string> {
  const validated = validateAgentEvent(event);
  const streamId = await redis.xadd(
    AGENT_EVENT_STREAM,
    "MAXLEN",
    "~",
    AGENT_EVENT_STREAM_MAXLEN,
    "*",
    "payload",
    JSON.stringify(validated),
  );
  if (streamId === null) {
    throw new Error("Redis did not return an event stream identity.");
  }
  return streamId;
}
