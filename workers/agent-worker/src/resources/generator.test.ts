import { createHash } from "node:crypto";

import { describe, expect, it, vi } from "vitest";

import { buildSourceBoundContext } from "../rag/source-bound.js";
import { generateResourceBundle } from "./generator.js";

const excerpt = "Python for statements iterate over the items of an iterable.";
const sourceId = "33333333-3333-4333-8333-333333333333";
const context = buildSourceBoundContext(
  {
    question: "Explain Python for loops",
    courseId: "69408047-3b99-5fb2-b383-81f7314ecd5d",
    nodeId: "9512e5ec-f547-51b3-b0df-c5b3a877da9e",
    allowedSourceIds: [sourceId],
  },
  [
    {
      sourceId,
      courseId: "69408047-3b99-5fb2-b383-81f7314ecd5d",
      nodeId: "9512e5ec-f547-51b3-b0df-c5b3a877da9e",
      title: "The for statement",
      url: "https://docs.python.org/3/reference/compound_stmts.html#the-for-statement",
      excerpt,
      excerptDigest: createHash("sha256").update(excerpt).digest("hex"),
      score: 1,
    },
  ],
);

const request = {
  jobId: "44444444-4444-4444-8444-444444444444",
  learningNeed: "Understand iteration order and range stop boundaries.",
  context,
  resourceTypes: [
    "MICRO_LECTURE",
    "STRUCTURE_CARD",
    "TRACE_ANIMATION",
    "LAYERED_EXERCISE",
    "NOTEBOOK_TASK",
  ] as const,
};

describe("progressive five-resource generation", () => {
  it("stages every resource in priority order and exposes partial progress immediately", async () => {
    const staged: Array<{ resourceType: string; content: Uint8Array }> = [];
    const progress: Array<{ status: string; percent: number }> = [];
    const result = await generateResourceBundle(request, {
      text: {
        generate: vi.fn().mockResolvedValue(`A source-bound explanation [source:${sourceId}]`),
      },
      sink: {
        async stage(artifact) {
          staged.push({ resourceType: artifact.resourceType, content: artifact.content });
        },
      },
      onProgress(event) {
        progress.push({ status: event.status, percent: event.percent });
      },
    });

    expect(staged.map((artifact) => artifact.resourceType)).toEqual([
      "STRUCTURE_CARD",
      "MICRO_LECTURE",
      "LAYERED_EXERCISE",
      "NOTEBOOK_TASK",
      "TRACE_ANIMATION",
    ]);
    expect(progress[0]).toEqual({ status: "PARTIAL_READY", percent: 20 });
    expect(progress.at(-1)).toEqual({ status: "READY", percent: 100 });
    expect(result.status).toBe("READY");
    expect(result.artifacts).toHaveLength(5);
    for (const artifact of result.artifacts) {
      expect(artifact.sourceIds).toEqual([sourceId]);
      expect(artifact.contextDigest).toBe(context.contextDigest);
      expect(artifact.contentDigest).toBe(
        createHash("sha256").update(artifact.content).digest("hex"),
      );
      expect(new TextDecoder().decode(artifact.content)).toContain(sourceId);
    }
    expect(result.artifacts.find((item) => item.resourceType === "TRACE_ANIMATION")?.mimeType).toBe(
      "image/svg+xml",
    );
    expect(staged.every((item) => !new TextDecoder().decode(item.content).includes("<video"))).toBe(
      true,
    );
  });

  it("falls back to a cited micro-lecture when the text Provider fails", async () => {
    const result = await generateResourceBundle(request, {
      text: { generate: vi.fn().mockRejectedValue(new Error("provider secret detail")) },
      sink: { stage: vi.fn().mockResolvedValue(undefined) },
    });

    const lecture = result.artifacts.find((item) => item.resourceType === "MICRO_LECTURE");
    expect(lecture?.fallbackUsed).toBe(true);
    expect(new TextDecoder().decode(lecture?.content)).toContain(`[source:${sourceId}]`);
    expect(JSON.stringify(result)).not.toContain("provider secret detail");
  });

  it("refuses an empty requested resource set before invoking providers", async () => {
    const generate = vi.fn();
    await expect(
      generateResourceBundle(
        { ...request, resourceTypes: [] },
        { text: { generate }, sink: { stage: vi.fn() } },
      ),
    ).rejects.toMatchObject({ code: "INVALID_RESOURCE_REQUEST" });
    expect(generate).not.toHaveBeenCalled();
  });
});
