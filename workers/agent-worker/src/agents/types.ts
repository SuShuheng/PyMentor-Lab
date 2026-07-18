import type {
  AgentAuditDetail,
  AgentAuditEventType,
  AgentNodeName,
  WorkerJobStatus,
} from "@pymentor/contracts";
import type { ZodType } from "zod";

import type { ToolRegistry } from "./tool-registry.js";

export type AgentFallbackReason = "INVALID_OUTPUT" | "PROVIDER_ERROR" | "TIMEOUT";

export interface AgentNodeDefinition<TInput, TOutput> {
  readonly name: AgentNodeName;
  readonly inputSchema: ZodType<TInput>;
  readonly outputSchema: ZodType<TOutput>;
  readonly allowedTools: readonly string[];
  readonly forbiddenPermissions: readonly string[];
  readonly timeoutMs: number;
  readonly fallback: (input: TInput, reason: AgentFallbackReason) => TOutput;
}

export interface AgentProviderRequest<TInput> {
  readonly node: AgentNodeName;
  readonly input: TInput;
  readonly repair: boolean;
  readonly signal: AbortSignal;
  readonly tools: {
    invoke(toolName: string, input: unknown): Promise<unknown>;
  };
}

export interface AgentProviderPort {
  complete<TInput>(request: AgentProviderRequest<TInput>): Promise<unknown>;
}

export interface AgentAuditRecord {
  readonly eventType: AgentAuditEventType;
  readonly eventId: string;
  readonly node: AgentNodeName;
  readonly toolName?: string;
  readonly status: WorkerJobStatus;
  readonly detail: Readonly<AgentAuditDetail>;
}

export interface AgentAuditSink {
  record(event: AgentAuditRecord): void | Promise<void>;
}

export interface AgentExecutionContext {
  readonly provider: AgentProviderPort;
  readonly audit: AgentAuditSink;
  readonly eventId: string;
  readonly tools: ToolRegistry;
  readonly nextToolSequence: () => number;
  readonly onOutcome?: (outcome: AgentExecutionOutcome) => void;
}

export interface AgentExecutionOutcome {
  readonly fallback: boolean;
  readonly retryCount: number;
  readonly code?: string;
}
