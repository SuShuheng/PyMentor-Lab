import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

describe("Windows release configuration", () => {
  it("enables ASAR integrity fuses and only the Windows Squirrel maker", async () => {
    const source = await readFile(resolve(packageRoot, "forge.config.ts"), "utf8");
    expect(source).toContain("asar: true");
    expect(source).toContain("MakerSquirrel");
    expect(source).toContain("RunAsNode]: false");
    expect(source).toContain("EnableNodeOptionsEnvironmentVariable]: false");
    expect(source).toContain("EnableNodeCliInspectArguments]: false");
    expect(source).toContain("EnableEmbeddedAsarIntegrityValidation]: true");
    expect(source).toContain("OnlyLoadAppFromAsar]: true");
    expect(source).toContain("LoadBrowserProcessSpecificV8Snapshot]: false");
    expect(source).toContain("GrantFileProtocolExtraPrivileges]: false");
    expect(source).toContain("WasmTrapHandlers]: true");
    expect(source).toContain("strictlyRequireAllFuses: true");
    expect(source).not.toContain("publishers:");
  });

  it("keeps the renderer entry at the Forge application root", async () => {
    const rendererConfig = await readFile(resolve(packageRoot, "vite.renderer.config.ts"), "utf8");
    const rendererEntry = await readFile(resolve(packageRoot, "index.html"), "utf8");

    expect(rendererConfig).not.toMatch(/\broot\s*:/);
    expect(rendererEntry).toContain("<main>");
  });
});
