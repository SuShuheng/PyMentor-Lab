import { describe, expect, it } from "vitest";

import { buildHealthApp } from "./health.js";

describe("agent-worker health", () => {
  it("GET /health returns the contract-shaped HealthResponse", async () => {
    const app = buildHealthApp({ now: () => "2026-07-17T00:00:00Z" });

    const res = await app.request("/health");

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({
      status: "ok",
      service: "agent-worker",
      version: "0.0.0",
      timestamp: "2026-07-17T00:00:00Z",
    });
  });

  it("always reports status ok at the bootstrap stage", async () => {
    const app = buildHealthApp();
    const res = await app.request("/health");
    const body = (await res.json()) as { status: string; service: string };
    expect(body.status).toBe("ok");
    expect(body.service).toBe("agent-worker");
  });
});
