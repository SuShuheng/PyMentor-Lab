import { createWriteStream } from "node:fs";
import { rename, rm } from "node:fs/promises";
import { basename, extname } from "node:path";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";

import {
  DesktopExportArtifactRequestSchema,
  isSafeArtifactName,
  type DesktopExportArtifactRequest,
  type DesktopExportArtifactResponse,
  type ErrorCode,
} from "@pymentor/contracts";

export const MAX_ARTIFACT_BYTES = 25 * 1024 * 1024;

const allowedMimeExtensions = new Map<string, ReadonlySet<string>>([
  ["text/plain", new Set([".txt", ".py"])],
  ["text/markdown", new Set([".md"])],
  ["application/json", new Set([".json", ".ipynb"])],
  ["application/x-ipynb+json", new Set([".ipynb"])],
  ["text/html", new Set([".html"])],
  ["application/pdf", new Set([".pdf"])],
  ["image/png", new Set([".png"])],
  ["image/jpeg", new Set([".jpg", ".jpeg"])],
  ["audio/mpeg", new Set([".mp3"])],
  ["audio/wav", new Set([".wav"])],
  ["text/vtt", new Set([".vtt"])],
  ["application/zip", new Set([".zip"])],
]);

export class ArtifactExportError extends Error {
  constructor(
    readonly code: ErrorCode,
    message: string,
    readonly retryable = false,
  ) {
    super(message);
    this.name = "ArtifactExportError";
  }
}

export interface ArtifactExportDependencies {
  chooseDestination(
    suggestedName: string,
  ): Promise<{ readonly canceled: true } | { readonly canceled: false; readonly filePath: string }>;
  fetchArtifact(artifactId: string, signal: AbortSignal): Promise<Response>;
  randomId(): string;
}

const cancellationError = (signal: AbortSignal): ArtifactExportError => {
  const reason = signal.reason;
  if (reason instanceof ArtifactExportError) return reason;
  if (
    typeof reason === "object" &&
    reason !== null &&
    "code" in reason &&
    (reason.code === "TIMEOUT" || reason.code === "CANCELLED")
  ) {
    return new ArtifactExportError(
      reason.code,
      reason.code === "TIMEOUT" ? "Export timed out" : "Export cancelled",
      true,
    );
  }
  return new ArtifactExportError("CANCELLED", "Export cancelled");
};

const assertActive = (signal: AbortSignal): void => {
  if (signal.aborted) throw cancellationError(signal);
};

const normalizedMime = (response: Response): string =>
  (response.headers.get("content-type") ?? "").split(";", 1)[0]?.trim().toLowerCase() ?? "";

const assertResponse = (response: Response, displayName: string): void => {
  if (!response.ok) {
    throw new ArtifactExportError("NOT_FOUND", "Artifact is not available");
  }
  const extensions = allowedMimeExtensions.get(normalizedMime(response));
  if (extensions === undefined || !extensions.has(extname(displayName).toLowerCase())) {
    throw new ArtifactExportError("IPC_CAPABILITY_DENIED", "Artifact type is not allowed");
  }
  const lengthHeader = response.headers.get("content-length");
  if (lengthHeader !== null) {
    const length = Number(lengthHeader);
    if (!Number.isSafeInteger(length) || length < 0 || length > MAX_ARTIFACT_BYTES) {
      throw new ArtifactExportError("IPC_CAPABILITY_DENIED", "Artifact exceeds the export limit");
    }
  }
  if (response.body === null) {
    throw new ArtifactExportError("INTERNAL_ERROR", "Artifact response is empty", true);
  }
};

export const exportArtifact = async (
  rawRequest: DesktopExportArtifactRequest,
  dependencies: ArtifactExportDependencies,
  signal: AbortSignal,
): Promise<DesktopExportArtifactResponse> => {
  const request = DesktopExportArtifactRequestSchema.parse(rawRequest);
  assertActive(signal);
  const destination = await dependencies.chooseDestination(request.suggestedName);
  if (destination.canceled) {
    return { status: "CANCELLED", displayName: request.suggestedName };
  }
  assertActive(signal);
  const displayName = basename(destination.filePath);
  if (!isSafeArtifactName(displayName)) {
    throw new ArtifactExportError("IPC_CAPABILITY_DENIED", "Export filename is not allowed");
  }
  const partialPath = `${destination.filePath}.pymentor-part-${dependencies.randomId()}`;
  try {
    const response = await dependencies.fetchArtifact(request.artifactId, signal);
    assertActive(signal);
    assertResponse(response, displayName);
    let received = 0;
    const limit = new Transform({
      transform(chunk: Buffer, _encoding, callback) {
        received += chunk.byteLength;
        if (received > MAX_ARTIFACT_BYTES) {
          callback(
            new ArtifactExportError("IPC_CAPABILITY_DENIED", "Artifact exceeds the export limit"),
          );
          return;
        }
        callback(null, chunk);
      },
    });
    const source = Readable.fromWeb(
      response.body as unknown as import("node:stream/web").ReadableStream<Uint8Array>,
    );
    await pipeline(source, limit, createWriteStream(partialPath, { flags: "wx", mode: 0o600 }), {
      signal,
    });
    assertActive(signal);
    await rename(partialPath, destination.filePath);
    return { status: "EXPORTED", displayName };
  } catch (error) {
    await rm(partialPath, { force: true }).catch(() => undefined);
    if (signal.aborted) throw cancellationError(signal);
    if (error instanceof ArtifactExportError) throw error;
    throw new ArtifactExportError("INTERNAL_ERROR", "Artifact export failed", true);
  }
};
