import { createHash } from "node:crypto";

import type { ZodType } from "zod";

import type { AgentAuditSink, AgentNodeDefinition } from "./types.js";

export interface ToolDefinition<TInput = unknown, TOutput = unknown> {
  readonly inputSchema: ZodType<TInput>;
  readonly outputSchema: ZodType<TOutput>;
  readonly invoke: (input: TInput, signal: AbortSignal, idempotencyKey: string) => Promise<TOutput>;
}

export interface ToolInvocationContext {
  readonly audit: AgentAuditSink;
  readonly eventId: string;
  readonly sequence: number;
  readonly signal: AbortSignal;
}

export class ToolRegistryError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ToolRegistryError";
  }
}

export class ToolRegistry {
  constructor(private readonly tools: Readonly<Record<string, ToolDefinition<any, any>>>) {}

  async invoke<TInput, TOutput>(
    definition: AgentNodeDefinition<TInput, TOutput>,
    toolName: string,
    input: unknown,
    context: ToolInvocationContext,
  ): Promise<unknown> {
    if (!definition.allowedTools.includes(toolName)) {
      await context.audit.record({
        eventType: "TOOL_FAILED",
        eventId: context.eventId,
        node: definition.name,
        toolName,
        status: "FAILED_FINAL",
        detail: { status: "FAILED_FINAL", code: "FORBIDDEN_TOOL" },
      });
      throw new ToolRegistryError(
        "FORBIDDEN_TOOL",
        `${definition.name} may not invoke ${toolName}.`,
      );
    }

    const tool = this.tools[toolName];
    if (tool === undefined) {
      throw new ToolRegistryError("UNKNOWN_TOOL", `Unknown tool: ${toolName}.`);
    }

    const parsedInput = tool.inputSchema.safeParse(input);
    if (!parsedInput.success) {
      await context.audit.record({
        eventType: "TOOL_FAILED",
        eventId: context.eventId,
        node: definition.name,
        toolName,
        status: "FAILED_FINAL",
        detail: { status: "FAILED_FINAL", code: "INVALID_TOOL_INPUT" },
      });
      throw new ToolRegistryError(
        "INVALID_TOOL_INPUT",
        `Input for ${toolName} did not match its contract.`,
      );
    }

    const startedAt = Date.now();
    const argumentMetrics = jsonMetrics(parsedInput.data);
    await context.audit.record({
      eventType: "TOOL_STARTED",
      eventId: context.eventId,
      node: definition.name,
      toolName,
      status: "RUNNING",
      detail: {
        status: "RUNNING",
        input_bytes: argumentMetrics.bytes,
        argument_digest: argumentMetrics.digest,
      },
    });

    const idempotencyKey = createHash("sha256")
      .update(`${context.eventId}|${definition.name}|${toolName}|${context.sequence}`)
      .digest("hex");

    try {
      if (context.signal.aborted) {
        throw new ToolRegistryError("TOOL_TIMEOUT", `${toolName} was aborted.`);
      }
      const rawOutput = await tool.invoke(parsedInput.data, context.signal, idempotencyKey);
      const parsedOutput = tool.outputSchema.safeParse(rawOutput);
      if (!parsedOutput.success) {
        throw new ToolRegistryError(
          "INVALID_TOOL_OUTPUT",
          `Output for ${toolName} did not match its contract.`,
        );
      }

      const resultMetrics = jsonMetrics(parsedOutput.data);
      await context.audit.record({
        eventType: "TOOL_COMPLETED",
        eventId: context.eventId,
        node: definition.name,
        toolName,
        status: "SUCCEEDED",
        detail: {
          status: "SUCCEEDED",
          output_bytes: resultMetrics.bytes,
          result_digest: resultMetrics.digest,
          latency_ms: latencySince(startedAt),
          retry_count: 0,
        },
      });
      return parsedOutput.data;
    } catch (error) {
      const code = context.signal.aborted
        ? "TOOL_TIMEOUT"
        : error instanceof ToolRegistryError
          ? error.code
          : "TOOL_FAILED";
      await context.audit.record({
        eventType: "TOOL_FAILED",
        eventId: context.eventId,
        node: definition.name,
        toolName,
        status: "FAILED_FINAL",
        detail: {
          status: "FAILED_FINAL",
          code,
          latency_ms: latencySince(startedAt),
          retry_count: 0,
        },
      });
      if (error instanceof ToolRegistryError && error.code === code) {
        throw error;
      }
      throw new ToolRegistryError(code, `${toolName} invocation failed.`);
    }
  }
}

function jsonMetrics(value: unknown): { bytes: number; digest: string } {
  const serialized = JSON.stringify(value);
  return {
    bytes: Buffer.byteLength(serialized, "utf8"),
    digest: createHash("sha256").update(serialized).digest("hex"),
  };
}

function latencySince(startedAt: number): number {
  return Math.min(3_600_000, Math.max(0, Math.round(Date.now() - startedAt)));
}
