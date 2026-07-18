import { randomUUID } from "node:crypto";

import {
  DesktopExportArtifactRequestSchema,
  DesktopExportArtifactResponseSchema,
  DesktopGetServerConfigRequestSchema,
  DesktopOpenExternalRequestSchema,
  DesktopOpenExternalResponseSchema,
  DesktopServerConfigRequestSchema,
  DesktopServerConfigResponseSchema,
  DesktopVersionRequestSchema,
  DesktopVersionResponseSchema,
  ErrorCode,
  desktopIpcChannels,
  type DesktopExportArtifactRequest,
  type DesktopExportArtifactResponse,
  type DesktopOpenExternalRequest,
  type DesktopOpenExternalResponse,
  type DesktopServerConfigRequest,
  type DesktopServerConfigResponse,
} from "@pymentor/contracts";
import { z } from "zod";

import { ArtifactExportError } from "../services/export-artifact.js";

interface SenderLike {
  once?(name: "destroyed", listener: () => void): this;
  removeListener?(name: "destroyed", listener: () => void): this;
}

interface IpcEventLike {
  readonly sender: SenderLike;
}

interface IpcMainLike {
  handle(channel: string, handler: (event: any, body?: unknown) => Promise<unknown>): void;
  removeHandler(channel: string): void;
}

export class DesktopOperationError extends Error {
  constructor(
    readonly code: ErrorCode,
    message: string,
    readonly retryable = false,
  ) {
    super(message);
    this.name = "DesktopOperationError";
  }
}

export interface DesktopIpcDependencies {
  readonly ipcMain: IpcMainLike;
  authorize(event: any): boolean;
  getVersion(): string;
  openExternal(
    body: DesktopOpenExternalRequest,
    signal: AbortSignal,
  ): Promise<DesktopOpenExternalResponse>;
  exportArtifact(
    body: DesktopExportArtifactRequest,
    signal: AbortSignal,
  ): Promise<DesktopExportArtifactResponse>;
  getServerConfig(signal: AbortSignal): Promise<DesktopServerConfigResponse>;
  setServerConfig(
    body: DesktopServerConfigRequest,
    signal: AbortSignal,
  ): Promise<DesktopServerConfigResponse>;
  readonly operationTimeoutMs: number;
  readonly rateLimitMaxRequests: number;
  readonly rateLimitWindowMs: number;
}

const errorResult = (code: ErrorCode, message: string, retryable = false) => ({
  ok: false as const,
  error: {
    code,
    message,
    trace_id: randomUUID(),
    retryable,
  },
});

const mapError = (error: unknown) => {
  if (error instanceof DesktopOperationError || error instanceof ArtifactExportError) {
    return errorResult(error.code, error.message, error.retryable);
  }
  if (error instanceof z.ZodError) {
    return errorResult("IPC_CAPABILITY_DENIED", "Desktop request was rejected");
  }
  if (error instanceof Error && "code" in error && "retryable" in error) {
    const code = ErrorCode.safeParse(error.code);
    if (code.success) {
      return errorResult(code.data, error.message, error.retryable === true);
    }
  }
  return errorResult("INTERNAL_ERROR", "Desktop operation failed", true);
};

const requestSize = (body: unknown): number =>
  Buffer.byteLength(JSON.stringify(body ?? null), "utf8");

const execute = async <TRequest, TResponse>(options: {
  readonly event: IpcEventLike;
  readonly body: unknown;
  readonly authorize: () => boolean;
  readonly consumeRateLimit: () => boolean;
  readonly requestSchema: z.ZodType<TRequest>;
  readonly responseSchema: z.ZodType<TResponse>;
  readonly timeoutMs: number;
  readonly operation: (request: TRequest, signal: AbortSignal) => Promise<TResponse> | TResponse;
}) => {
  if (!options.authorize())
    return errorResult("IPC_INVALID_SENDER", "Desktop sender is not trusted");
  if (!options.consumeRateLimit()) {
    return errorResult("IPC_CAPABILITY_DENIED", "Desktop request rate limit exceeded", true);
  }
  if (requestSize(options.body) > 4_096) {
    return errorResult("IPC_CAPABILITY_DENIED", "Desktop request exceeds the size limit");
  }
  const controller = new AbortController();
  const cancelForDestroyedSender = (): void => {
    controller.abort(new DesktopOperationError("CANCELLED", "Desktop operation cancelled"));
  };
  options.event.sender.once?.("destroyed", cancelForDestroyedSender);
  const timer = setTimeout(() => {
    controller.abort(new DesktopOperationError("TIMEOUT", "Desktop operation timed out", true));
  }, options.timeoutMs);
  try {
    const request = options.requestSchema.parse(options.body);
    const response = options.responseSchema.parse(
      await options.operation(request, controller.signal),
    );
    if (requestSize(response) > 4_096) {
      throw new DesktopOperationError(
        "IPC_CAPABILITY_DENIED",
        "Desktop response exceeds the size limit",
      );
    }
    return { ok: true as const, value: response };
  } catch (error) {
    if (controller.signal.aborted && controller.signal.reason instanceof DesktopOperationError) {
      return mapError(controller.signal.reason);
    }
    return mapError(error);
  } finally {
    clearTimeout(timer);
    options.event.sender.removeListener?.("destroyed", cancelForDestroyedSender);
  }
};

export const registerDesktopIpc = (dependencies: DesktopIpcDependencies): (() => void) => {
  const channels = Object.values(desktopIpcChannels);
  const senderRates = new WeakMap<object, { count: number; windowStartedAt: number }>();
  const consumeRateLimit = (sender: object): boolean => {
    const now = Date.now();
    const current = senderRates.get(sender);
    if (current === undefined || now - current.windowStartedAt >= dependencies.rateLimitWindowMs) {
      senderRates.set(sender, { count: 1, windowStartedAt: now });
      return true;
    }
    current.count += 1;
    return current.count <= dependencies.rateLimitMaxRequests;
  };
  const register = <TRequest, TResponse>(
    channel: string,
    requestSchema: z.ZodType<TRequest>,
    responseSchema: z.ZodType<TResponse>,
    operation: (request: TRequest, signal: AbortSignal) => Promise<TResponse> | TResponse,
  ): void => {
    dependencies.ipcMain.handle(channel, async (event, body) =>
      execute({
        event,
        body,
        authorize: () => dependencies.authorize(event),
        consumeRateLimit: () => consumeRateLimit(event.sender),
        requestSchema,
        responseSchema,
        timeoutMs: dependencies.operationTimeoutMs,
        operation,
      }),
    );
  };

  register(
    desktopIpcChannels.getVersion,
    DesktopVersionRequestSchema,
    DesktopVersionResponseSchema,
    () => ({
      version: dependencies.getVersion(),
    }),
  );
  register(
    desktopIpcChannels.openExternal,
    DesktopOpenExternalRequestSchema,
    DesktopOpenExternalResponseSchema,
    dependencies.openExternal,
  );
  register(
    desktopIpcChannels.exportArtifact,
    DesktopExportArtifactRequestSchema,
    DesktopExportArtifactResponseSchema,
    dependencies.exportArtifact,
  );
  register(
    desktopIpcChannels.getServerConfig,
    DesktopGetServerConfigRequestSchema,
    DesktopServerConfigResponseSchema,
    (_request, signal) => dependencies.getServerConfig(signal),
  );
  register(
    desktopIpcChannels.setServerConfig,
    DesktopServerConfigRequestSchema,
    DesktopServerConfigResponseSchema,
    dependencies.setServerConfig,
  );

  return () => {
    for (const channel of channels) dependencies.ipcMain.removeHandler(channel);
  };
};
