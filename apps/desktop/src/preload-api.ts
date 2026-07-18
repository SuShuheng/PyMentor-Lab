import {
  DesktopExportArtifactRequestSchema,
  DesktopExportArtifactResponseSchema,
  DesktopOpenExternalRequestSchema,
  DesktopOpenExternalResponseSchema,
  DesktopServerConfigRequestSchema,
  DesktopServerConfigResponseSchema,
  DesktopVersionResponseSchema,
  desktopIpcChannels,
  desktopIpcResultSchema,
  type DesktopExportArtifactRequest,
  type DesktopExportArtifactResponse,
  type DesktopIpcResult,
  type DesktopOpenExternalRequest,
  type DesktopOpenExternalResponse,
  type DesktopServerConfigRequest,
  type DesktopServerConfigResponse,
  type DesktopVersionResponse,
  type ErrorCode,
} from "@pymentor/contracts";
import type { z } from "zod";

type Invoke = (channel: string, body?: unknown) => Promise<unknown>;

export class DesktopIpcError extends Error {
  constructor(
    readonly code: ErrorCode,
    message: string,
    readonly traceId: string,
    readonly retryable: boolean,
  ) {
    super(message);
    this.name = "DesktopIpcError";
  }
}

const unwrap = <T extends z.ZodTypeAny>(schema: T, raw: unknown): z.infer<T> => {
  const result = desktopIpcResultSchema(schema).safeParse(raw);
  if (!result.success) throw new Error("Invalid desktop response");
  const data = result.data as DesktopIpcResult<z.infer<T>>;
  if (!data.ok) {
    throw new DesktopIpcError(
      data.error.code,
      data.error.message,
      data.error.trace_id,
      data.error.retryable,
    );
  }
  return data.value;
};

export interface DesktopBridge {
  getVersion(): Promise<DesktopVersionResponse>;
  openExternal(body: DesktopOpenExternalRequest): Promise<DesktopOpenExternalResponse>;
  exportArtifact(body: DesktopExportArtifactRequest): Promise<DesktopExportArtifactResponse>;
  getServerConfig(): Promise<DesktopServerConfigResponse>;
  setServerConfig(body: DesktopServerConfigRequest): Promise<DesktopServerConfigResponse>;
}

export const createDesktopBridge = (invoke: Invoke): DesktopBridge =>
  Object.freeze({
    async getVersion() {
      return unwrap(DesktopVersionResponseSchema, await invoke(desktopIpcChannels.getVersion));
    },
    async openExternal(body: DesktopOpenExternalRequest) {
      const request = DesktopOpenExternalRequestSchema.parse(body);
      return unwrap(
        DesktopOpenExternalResponseSchema,
        await invoke(desktopIpcChannels.openExternal, request),
      );
    },
    async exportArtifact(body: DesktopExportArtifactRequest) {
      const request = DesktopExportArtifactRequestSchema.parse(body);
      return unwrap(
        DesktopExportArtifactResponseSchema,
        await invoke(desktopIpcChannels.exportArtifact, request),
      );
    },
    async getServerConfig() {
      return unwrap(
        DesktopServerConfigResponseSchema,
        await invoke(desktopIpcChannels.getServerConfig),
      );
    },
    async setServerConfig(body: DesktopServerConfigRequest) {
      const request = DesktopServerConfigRequestSchema.parse(body);
      return unwrap(
        DesktopServerConfigResponseSchema,
        await invoke(desktopIpcChannels.setServerConfig, request),
      );
    },
  });
