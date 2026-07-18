import { createHash } from "node:crypto";

import type {
  AgentAuditRecord,
  AgentExecutionContext,
  AgentFallbackReason,
  AgentNodeDefinition,
} from "./types.js";
import { ToolRegistryError } from "./tool-registry.js";

class AgentExecutionTimeout extends Error {}

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

export class AgentExecutionError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "AgentExecutionError";
  }
}

export async function executeNode<TInput, TOutput>(
  definition: AgentNodeDefinition<TInput, TOutput>,
  input: unknown,
  context: AgentExecutionContext,
): Promise<TOutput> {
  const parsed = definition.inputSchema.safeParse(input);
  if (!parsed.success) {
    throw new AgentExecutionError(
      "INVALID_INPUT",
      `Input for ${definition.name} did not match its contract.`,
    );
  }

  const startedAt = Date.now();
  const inputMetrics = jsonMetrics(parsed.data);
  await context.audit.record({
    eventType: "NODE_STARTED",
    eventId: context.eventId,
    node: definition.name,
    status: "RUNNING",
    detail: {
      status: "RUNNING",
      input_bytes: inputMetrics.bytes,
      argument_digest: inputMetrics.digest,
    },
  });

  const controller = new AbortController();
  let toolsActive = true;
  let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    timeoutHandle = setTimeout(() => {
      controller.abort();
      reject(new AgentExecutionTimeout());
    }, definition.timeoutMs);
  });

  const completeWithAudit = async (
    output: TOutput,
    retryCount: number,
    fallback: boolean,
    code?: string,
  ): Promise<TOutput> => {
    const outputMetrics = jsonMetrics(output);
    const detail: AgentAuditRecord["detail"] = {
      status: "SUCCEEDED",
      output_bytes: outputMetrics.bytes,
      result_digest: outputMetrics.digest,
      latency_ms: latencySince(startedAt),
      retry_count: retryCount,
      fallback,
      ...(code === undefined ? {} : { code }),
    };
    await context.audit.record({
      eventType: "NODE_COMPLETED",
      eventId: context.eventId,
      node: definition.name,
      status: "SUCCEEDED",
      detail,
    });
    context.onOutcome?.({
      fallback,
      retryCount,
      ...(code === undefined ? {} : { code }),
    });
    return output;
  };

  const fallbackWithAudit = async (
    reason: AgentFallbackReason,
    retryCount: number,
  ): Promise<TOutput> => {
    const fallback = definition.outputSchema.safeParse(definition.fallback(parsed.data, reason));
    if (!fallback.success) {
      throw new AgentExecutionError(
        "INVALID_FALLBACK",
        `Fallback for ${definition.name} did not match its output contract.`,
      );
    }
    return completeWithAudit(fallback.data, retryCount, true, reason);
  };

  try {
    for (const [retryCount, repair] of [false, true].entries()) {
      const output = await Promise.race([
        context.provider.complete({
          node: definition.name,
          input: parsed.data,
          repair,
          signal: controller.signal,
          tools: {
            invoke: async (toolName, toolInput) => {
              if (!toolsActive || controller.signal.aborted) {
                throw new ToolRegistryError(
                  "TOOL_TIMEOUT",
                  `${definition.name} tool capability is no longer active.`,
                );
              }
              return await context.tools.invoke(definition, toolName, toolInput, {
                audit: context.audit,
                eventId: context.eventId,
                sequence: context.nextToolSequence(),
                signal: controller.signal,
              });
            },
          },
        }),
        deadline,
      ]);
      const validated = definition.outputSchema.safeParse(output);
      if (validated.success) {
        return await completeWithAudit(validated.data, retryCount, false);
      }
    }

    return await fallbackWithAudit("INVALID_OUTPUT", 1);
  } catch (error) {
    if (error instanceof ToolRegistryError) {
      throw error;
    }
    if (error instanceof AgentExecutionError && error.code === "INVALID_FALLBACK") {
      throw error;
    }
    if (error instanceof AgentExecutionTimeout) {
      return await fallbackWithAudit("TIMEOUT", 0);
    }
    return await fallbackWithAudit("PROVIDER_ERROR", 0);
  } finally {
    toolsActive = false;
    controller.abort();
    if (timeoutHandle !== undefined) {
      clearTimeout(timeoutHandle);
    }
  }
}
