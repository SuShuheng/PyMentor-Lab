import { Hono } from "hono";
import { describe, expect, it } from "vitest";

import { createResourceGenerationHandler } from "./http.js";

const secret = "test-worker-internal-secret-at-least-32-characters";

function app() {
  const instance = new Hono();
  instance.post("/generate", createResourceGenerationHandler(secret));
  return instance;
}

const body = {
  context: {
    citations: [
      {
        excerptDigest: "a".repeat(64),
        sourceId: "source-1",
        title: "Governed Python source",
        url: "https://example.edu/python",
      },
    ],
    contextDigest: "b".repeat(64),
    prompt: "Use only [source:source-1].",
    question: "Explain loop boundaries.",
  },
  job_id: "job-1",
  learning_need: "Understand the exclusive stop boundary.",
  resource_types: ["STRUCTURE_CARD", "MICRO_LECTURE"],
};

describe("internal resource generation", () => {
  it("rejects callers outside the authenticated service boundary", async () => {
    const response = await app().request("/generate", {
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    });

    expect(response.status).toBe(401);
  });

  it("returns source-bound artifacts and a bounded provider fallback", async () => {
    const response = await app().request("/generate", {
      body: JSON.stringify(body),
      headers: {
        Authorization: `Bearer ${secret}`,
        "Content-Type": "application/json",
      },
      method: "POST",
    });

    expect(response.status).toBe(200);
    const result = (await response.json()) as {
      artifacts: Array<{
        content_base64: string;
        fallback_used: boolean;
        resource_type: string;
        source_ids: string[];
      }>;
      status: string;
    };
    expect(result.status).toBe("READY");
    expect(result.artifacts.map((item) => item.resource_type)).toEqual([
      "STRUCTURE_CARD",
      "MICRO_LECTURE",
    ]);
    expect(result.artifacts.every((item) => item.source_ids[0] === "source-1")).toBe(true);
    expect(
      result.artifacts.find((item) => item.resource_type === "MICRO_LECTURE")?.fallback_used,
    ).toBe(true);
    expect(result.artifacts.every((item) => item.content_base64.length > 0)).toBe(true);
  });
});
