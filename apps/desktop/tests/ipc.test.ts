import { EventEmitter } from "node:events";

import { desktopIpcChannels, type DesktopExportArtifactResponse } from "@pymentor/contracts";
import { describe, expect, it, vi } from "vitest";

import { registerDesktopIpc } from "../src/ipc/register.js";

class FakeIpcMain {
  readonly handlers = new Map<string, (event: unknown, body?: unknown) => Promise<unknown>>();
  readonly removeHandler = vi.fn((channel: string) => this.handlers.delete(channel));

  handle(channel: string, handler: (event: unknown, body?: unknown) => Promise<unknown>): void {
    this.handlers.set(channel, handler);
  }
}

describe("desktop IPC registration", () => {
  const rateLimit = {
    rateLimitMaxRequests: 60,
    rateLimitWindowMs: 10_000,
  };

  it("rejects untrusted senders before invoking privileged services", async () => {
    const ipcMain = new FakeIpcMain();
    const openExternal = vi.fn();
    registerDesktopIpc({
      ipcMain,
      authorize: () => false,
      getVersion: () => "0.1.0",
      openExternal,
      exportArtifact: vi.fn(),
      getServerConfig: vi.fn(),
      setServerConfig: vi.fn(),
      operationTimeoutMs: 1_000,
      ...rateLimit,
    });
    const result = await ipcMain.handlers.get(desktopIpcChannels.openExternal)?.(
      { sender: new EventEmitter() },
      { url: "https://example.edu" },
    );
    expect(result).toMatchObject({ ok: false, error: { code: "IPC_INVALID_SENDER" } });
    expect(openExternal).not.toHaveBeenCalled();
  });

  it("bounds operations, cancels on sender destruction and cleans listeners/handlers", async () => {
    vi.useFakeTimers();
    const ipcMain = new FakeIpcMain();
    const sender = new EventEmitter();
    const exportArtifact = vi.fn(
      async (_body, signal: AbortSignal): Promise<DesktopExportArtifactResponse> => {
        await new Promise<void>((resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason), { once: true });
        });
        throw new Error("unreachable");
      },
    );
    const dispose = registerDesktopIpc({
      ipcMain,
      authorize: () => true,
      getVersion: () => "0.1.0",
      openExternal: vi.fn(),
      exportArtifact,
      getServerConfig: vi.fn(),
      setServerConfig: vi.fn(),
      operationTimeoutMs: 50,
      ...rateLimit,
    });
    const pending = ipcMain.handlers.get(desktopIpcChannels.exportArtifact)?.(
      { sender },
      {
        artifactId: "3f1c7b2d-7b83-4e8c-b3bd-3d5af629a902",
        suggestedName: "lesson.pdf",
      },
    );
    await vi.advanceTimersByTimeAsync(51);
    await expect(pending).resolves.toMatchObject({ ok: false, error: { code: "TIMEOUT" } });
    expect(sender.listenerCount("destroyed")).toBe(0);
    dispose();
    expect(ipcMain.removeHandler).toHaveBeenCalledTimes(5);
    vi.useRealTimers();
  });

  it("validates requests and returns only serializable bounded envelopes", async () => {
    const ipcMain = new FakeIpcMain();
    registerDesktopIpc({
      ipcMain,
      authorize: () => true,
      getVersion: () => "0.1.0",
      openExternal: vi.fn(async () => ({ opened: true })),
      exportArtifact: vi.fn(),
      getServerConfig: vi.fn(async () => ({ baseUrl: null })),
      setServerConfig: vi.fn(),
      operationTimeoutMs: 1_000,
      ...rateLimit,
    });
    const invalid = await ipcMain.handlers.get(desktopIpcChannels.openExternal)?.(
      { sender: new EventEmitter() },
      { url: "file:///secret", extra: "x" },
    );
    expect(invalid).toMatchObject({ ok: false, error: { code: "IPC_CAPABILITY_DENIED" } });
  });

  it("rate-limits a trusted sender across capability channels", async () => {
    const ipcMain = new FakeIpcMain();
    const sender = new EventEmitter();
    const openExternal = vi.fn(async () => ({ opened: true }));
    registerDesktopIpc({
      ipcMain,
      authorize: () => true,
      getVersion: () => "0.1.0",
      openExternal,
      exportArtifact: vi.fn(),
      getServerConfig: vi.fn(async () => ({ baseUrl: null })),
      setServerConfig: vi.fn(),
      operationTimeoutMs: 1_000,
      rateLimitMaxRequests: 1,
      rateLimitWindowMs: 10_000,
    });

    await ipcMain.handlers.get(desktopIpcChannels.getVersion)?.({ sender });
    const result = await ipcMain.handlers.get(desktopIpcChannels.openExternal)?.(
      { sender },
      { url: "https://example.edu" },
    );

    expect(result).toMatchObject({
      ok: false,
      error: { code: "IPC_CAPABILITY_DENIED", retryable: true },
    });
    expect(openExternal).not.toHaveBeenCalled();
  });
});
