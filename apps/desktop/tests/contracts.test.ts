import {
  DesktopExportArtifactRequestSchema,
  DesktopOpenExternalRequestSchema,
  DesktopServerConfigRequestSchema,
  desktopIpcChannels,
} from "@pymentor/contracts";
import { describe, expect, it } from "vitest";

describe("desktop shared contracts", () => {
  it("publishes only the five fixed IPC channels", () => {
    expect(desktopIpcChannels).toEqual({
      getVersion: "desktop:version",
      openExternal: "desktop:open-external",
      exportArtifact: "desktop:export-artifact",
      getServerConfig: "desktop:get-server-config",
      setServerConfig: "desktop:set-server-config",
    });
  });

  it("rejects unknown fields and unsafe external URLs", () => {
    expect(() =>
      DesktopOpenExternalRequestSchema.parse({ url: "https://example.edu", extra: true }),
    ).toThrow();
    for (const url of [
      "http://example.edu",
      "file:///C:/secrets.txt",
      "javascript:alert(1)",
      "https://user:pass@example.edu",
    ]) {
      expect(() => DesktopOpenExternalRequestSchema.parse({ url })).toThrow();
    }
  });

  it("rejects traversal, executable, control-character and oversized names", () => {
    for (const suggestedName of [
      "../notes.txt",
      "folder/notes.txt",
      "folder\\notes.txt",
      "lesson.exe",
      "lesson\u0000.txt",
      `${"a".repeat(121)}.txt`,
    ]) {
      expect(() =>
        DesktopExportArtifactRequestSchema.parse({
          artifactId: "3f1c7b2d-7b83-4e8c-b3bd-3d5af629a902",
          suggestedName,
        }),
      ).toThrow();
    }
  });

  it("allows HTTPS and explicit local/private HTTP API roots only", () => {
    for (const baseUrl of [
      "https://api.example.edu",
      "http://127.0.0.1:8000",
      "http://localhost:8000",
      "http://192.168.1.20:8000",
      "http://[fd00::1]:8000",
      "http://[fe80::1]:8000",
      "http://pymentor.local:8000",
    ]) {
      expect(DesktopServerConfigRequestSchema.parse({ baseUrl })).toEqual({ baseUrl });
    }
    for (const baseUrl of [
      "http://example.edu",
      "http://fcorp.example",
      "http://fdomain.example",
      "ftp://127.0.0.1",
      "https://user:pass@example.edu",
      "https://example.edu/path",
    ]) {
      expect(() => DesktopServerConfigRequestSchema.parse({ baseUrl })).toThrow();
    }
  });
});
