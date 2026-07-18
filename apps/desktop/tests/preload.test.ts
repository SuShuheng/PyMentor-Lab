import { describe, expect, it, vi } from "vitest";

import { desktopIpcChannels } from "@pymentor/contracts";

import { createDesktopBridge } from "../src/preload-api.js";

describe("preload public surface", () => {
  it("exposes exactly five named capabilities using fixed channels", async () => {
    const invoke = vi.fn(async (channel: string) => {
      if (channel === desktopIpcChannels.getVersion)
        return { ok: true, value: { version: "0.1.0" } };
      if (channel === desktopIpcChannels.openExternal) return { ok: true, value: { opened: true } };
      if (channel === desktopIpcChannels.exportArtifact) {
        return { ok: true, value: { status: "CANCELLED", displayName: "lesson.pdf" } };
      }
      return { ok: true, value: { baseUrl: null } };
    });
    const desktop = createDesktopBridge(invoke);
    expect(Object.keys(desktop).sort()).toEqual([
      "exportArtifact",
      "getServerConfig",
      "getVersion",
      "openExternal",
      "setServerConfig",
    ]);

    await desktop.getVersion();
    await desktop.openExternal({ url: "https://docs.python.org/3/" });
    await desktop.exportArtifact({
      artifactId: "3f1c7b2d-7b83-4e8c-b3bd-3d5af629a902",
      suggestedName: "lesson.pdf",
    });
    await desktop.getServerConfig();
    await desktop.setServerConfig({ baseUrl: "https://api.example.edu" });

    expect(invoke.mock.calls.map(([channel]) => channel)).toEqual(
      Object.values(desktopIpcChannels),
    );
  });

  it("validates input before invoke and rejects malformed result envelopes", async () => {
    const invoke = vi.fn(async () => ({ ok: true, value: { opened: "yes" } }));
    const desktop = createDesktopBridge(invoke);
    await expect(desktop.openExternal({ url: "file:///tmp/a" })).rejects.toThrow();
    expect(invoke).not.toHaveBeenCalled();
    await expect(desktop.openExternal({ url: "https://example.edu" })).rejects.toThrow(
      "Invalid desktop response",
    );
  });
});
