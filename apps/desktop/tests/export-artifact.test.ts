import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ArtifactExportError,
  exportArtifact,
  type ArtifactExportDependencies,
} from "../src/services/export-artifact.js";

const temporaryDirectories: string[] = [];

async function tempDirectory(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), "pymentor-desktop-test-"));
  temporaryDirectories.push(directory);
  return directory;
}

afterEach(async () => {
  const { rm } = await import("node:fs/promises");
  await Promise.all(temporaryDirectories.splice(0).map((path) => rm(path, { recursive: true })));
});

function dependencies(
  overrides: Partial<ArtifactExportDependencies> = {},
): ArtifactExportDependencies {
  return {
    chooseDestination: vi.fn(async () => ({ canceled: true as const })),
    fetchArtifact: vi.fn(
      async () => new Response("lesson", { headers: { "content-type": "text/plain" } }),
    ),
    randomId: () => "fixed",
    ...overrides,
  };
}

describe("controlled artifact export", () => {
  it("does not fetch when the native save dialog is cancelled", async () => {
    const deps = dependencies();
    await expect(
      exportArtifact(
        {
          artifactId: "3f1c7b2d-7b83-4e8c-b3bd-3d5af629a902",
          suggestedName: "lesson.txt",
        },
        deps,
        AbortSignal.timeout(1_000),
      ),
    ).resolves.toEqual({ status: "CANCELLED", displayName: "lesson.txt" });
    expect(deps.fetchArtifact).not.toHaveBeenCalled();
  });

  it("streams an allowlisted MIME type through a partial file and atomically completes", async () => {
    const directory = await tempDirectory();
    const destination = join(directory, "lesson.txt");
    const deps = dependencies({
      chooseDestination: vi.fn(async () => ({ canceled: false, filePath: destination })),
    });
    await expect(
      exportArtifact(
        {
          artifactId: "3f1c7b2d-7b83-4e8c-b3bd-3d5af629a902",
          suggestedName: "lesson.txt",
        },
        deps,
        AbortSignal.timeout(1_000),
      ),
    ).resolves.toEqual({ status: "EXPORTED", displayName: "lesson.txt" });
    await expect(readFile(destination, "utf8")).resolves.toBe("lesson");
  });

  it("rejects bad MIME, oversized content, timeout and removes partial output", async () => {
    const directory = await tempDirectory();
    const destination = join(directory, "lesson.txt");
    for (const response of [
      new Response("binary", { headers: { "content-type": "application/x-msdownload" } }),
      new Response("x", {
        headers: { "content-type": "text/plain", "content-length": String(25 * 1024 * 1024 + 1) },
      }),
    ]) {
      const deps = dependencies({
        chooseDestination: vi.fn(async () => ({ canceled: false, filePath: destination })),
        fetchArtifact: vi.fn(async () => response),
      });
      await expect(
        exportArtifact(
          {
            artifactId: "3f1c7b2d-7b83-4e8c-b3bd-3d5af629a902",
            suggestedName: "lesson.txt",
          },
          deps,
          AbortSignal.timeout(1_000),
        ),
      ).rejects.toBeInstanceOf(ArtifactExportError);
      await expect(readFile(`${destination}.pymentor-part-fixed`)).rejects.toMatchObject({
        code: "ENOENT",
      });
    }

    await writeFile(destination, "old");
    const aborted = new AbortController();
    aborted.abort();
    await expect(
      exportArtifact(
        {
          artifactId: "3f1c7b2d-7b83-4e8c-b3bd-3d5af629a902",
          suggestedName: "lesson.txt",
        },
        dependencies({
          chooseDestination: vi.fn(async () => ({ canceled: false, filePath: destination })),
        }),
        aborted.signal,
      ),
    ).rejects.toMatchObject({ code: "CANCELLED" });
    await expect(readFile(destination, "utf8")).resolves.toBe("old");
  });
});
