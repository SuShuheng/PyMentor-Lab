import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import {
  DesktopServerConfigRequestSchema,
  DesktopServerConfigResponseSchema,
  type DesktopServerConfigRequest,
  type DesktopServerConfigResponse,
  type ErrorCode,
} from "@pymentor/contracts";

const MAX_CONFIG_BYTES = 4_096;

export class ServerConfigError extends Error {
  constructor(
    readonly code: ErrorCode,
    message: string,
    readonly retryable = false,
  ) {
    super(message);
    this.name = "ServerConfigError";
  }
}

const assertActive = (signal: AbortSignal): void => {
  if (signal.aborted) throw new ServerConfigError("CANCELLED", "Server configuration cancelled");
};

export class ServerConfigStore {
  constructor(
    private readonly configPath: string,
    private readonly randomId: () => string,
  ) {}

  async get(signal: AbortSignal): Promise<DesktopServerConfigResponse> {
    assertActive(signal);
    try {
      const content = await readFile(this.configPath);
      assertActive(signal);
      if (content.byteLength > MAX_CONFIG_BYTES) return { baseUrl: null };
      const decoded: unknown = JSON.parse(content.toString("utf8"));
      const parsed = DesktopServerConfigResponseSchema.safeParse(decoded);
      return parsed.success ? parsed.data : { baseUrl: null };
    } catch (error) {
      if (signal.aborted)
        throw new ServerConfigError("CANCELLED", "Server configuration cancelled");
      if (
        typeof error === "object" &&
        error !== null &&
        "code" in error &&
        error.code === "ENOENT"
      ) {
        return { baseUrl: null };
      }
      return { baseUrl: null };
    }
  }

  async set(
    rawRequest: DesktopServerConfigRequest,
    signal: AbortSignal,
  ): Promise<DesktopServerConfigResponse> {
    const request = DesktopServerConfigRequestSchema.parse(rawRequest);
    assertActive(signal);
    const encoded = Buffer.from(JSON.stringify(request), "utf8");
    if (encoded.byteLength > MAX_CONFIG_BYTES) {
      throw new ServerConfigError("IPC_CAPABILITY_DENIED", "Server configuration is too large");
    }
    const partialPath = `${this.configPath}.pymentor-part-${this.randomId()}`;
    await mkdir(dirname(this.configPath), { recursive: true });
    try {
      assertActive(signal);
      await writeFile(partialPath, encoded, { flag: "wx", mode: 0o600 });
      assertActive(signal);
      await rename(partialPath, this.configPath);
      return { baseUrl: request.baseUrl };
    } catch (error) {
      await rm(partialPath, { force: true }).catch(() => undefined);
      if (signal.aborted)
        throw new ServerConfigError("CANCELLED", "Server configuration cancelled");
      if (error instanceof ServerConfigError) throw error;
      throw new ServerConfigError(
        "INTERNAL_ERROR",
        "Server configuration could not be saved",
        true,
      );
    }
  }
}
