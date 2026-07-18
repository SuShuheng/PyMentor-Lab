import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { ServerConfigStore } from "../src/services/server-config.js";

const directories: string[] = [];

afterEach(async () => {
  await Promise.all(directories.splice(0).map((path) => rm(path, { recursive: true })));
});

describe("non-secret server configuration", () => {
  it("persists only a validated base URL using an atomic private file", async () => {
    const directory = await mkdtemp(join(tmpdir(), "pymentor-config-test-"));
    directories.push(directory);
    const path = join(directory, "server-config.json");
    const store = new ServerConfigStore(path, () => "fixed");
    await expect(store.get(AbortSignal.timeout(1_000))).resolves.toEqual({ baseUrl: null });
    await expect(
      store.set({ baseUrl: "https://api.example.edu" }, AbortSignal.timeout(1_000)),
    ).resolves.toEqual({ baseUrl: "https://api.example.edu" });
    expect(JSON.parse(await readFile(path, "utf8"))).toEqual({
      baseUrl: "https://api.example.edu",
    });
    await expect(store.get(AbortSignal.timeout(1_000))).resolves.toEqual({
      baseUrl: "https://api.example.edu",
    });
    await expect(
      store.set({ baseUrl: "https://api-2.example.edu" }, AbortSignal.timeout(1_000)),
    ).resolves.toEqual({ baseUrl: "https://api-2.example.edu" });
    expect(JSON.parse(await readFile(path, "utf8"))).toEqual({
      baseUrl: "https://api-2.example.edu",
    });
  });

  it("fails closed for malformed/oversized data and preserves prior data on cancellation", async () => {
    const directory = await mkdtemp(join(tmpdir(), "pymentor-config-test-"));
    directories.push(directory);
    const path = join(directory, "server-config.json");
    const store = new ServerConfigStore(path, () => "fixed");
    await writeFile(path, "x".repeat(4_097));
    await expect(store.get(AbortSignal.timeout(1_000))).resolves.toEqual({ baseUrl: null });
    await writeFile(path, JSON.stringify({ baseUrl: "https://api.example.edu" }));
    const aborted = new AbortController();
    aborted.abort();
    await expect(
      store.set({ baseUrl: "https://new.example.edu" }, aborted.signal),
    ).rejects.toMatchObject({
      code: "CANCELLED",
    });
    expect(JSON.parse(await readFile(path, "utf8"))).toEqual({
      baseUrl: "https://api.example.edu",
    });
  });
});
