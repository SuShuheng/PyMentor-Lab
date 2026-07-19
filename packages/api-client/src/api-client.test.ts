import { describe, expect, expectTypeOf, it } from "vitest";

import type {
  HealthResponse,
  HealthStatus,
  ProfileSnapshot,
  SystemPingResponse,
} from "./generated/types.gen";

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

  it("exposes the immutable profile identity required by disputes", () => {
    const profile: ProfileSnapshot = {
      dimensions: [],
      id: "00000000-0000-0000-0000-000000000031",
      source_event_id: "evt-profile-1",
      student_id: "00000000-0000-0000-0000-000000000030",
      version: 1,
    };

    expect(profile.id).toBe("00000000-0000-0000-0000-000000000031");
  });
});
