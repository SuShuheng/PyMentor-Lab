import { describe, expect, expectTypeOf, it } from "vitest";

import type { HealthResponse, HealthStatus, SystemPingResponse } from "./generated/types.gen";

describe("generated api-client", () => {
  it("exposes the contract health types", () => {
    // Compile-time assertion that the generated client mirrors the backend.
    expectTypeOf<HealthStatus>().toEqualTypeOf<"ok" | "degraded" | "down">();

    const sample: HealthResponse = {
      status: "ok",
      service: "api",
      version: "0.0.0",
      timestamp: "2026-07-17T00:00:00Z",
    };
    expect(sample.status).toBe("ok");
  });

  it("exposes the system ping type", () => {
    const ping: SystemPingResponse = {
      ok: true,
      service: "api",
      timestamp: "2026-07-17T00:00:00Z",
    };
    expect(ping.ok).toBe(true);
  });
});
