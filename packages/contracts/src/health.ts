/**
 * Service health and connectivity contracts.
 * Field names MUST stay in lock-step with `backend/app/contracts/health.py`.
 */

import { z } from "zod";

/** Overall service health for liveness/readiness probes. */
export const HealthStatus = z.enum(["ok", "degraded", "down"]);
export type HealthStatus = z.infer<typeof HealthStatus>;

/** Body of `GET /health`. */
export const HealthResponse = z.object({
  status: HealthStatus,
  service: z.string().min(1),
  version: z.string().min(1),
  /** ISO-8601 timestamp in UTC. */
  timestamp: z.string().min(1),
});
export type HealthResponse = z.infer<typeof HealthResponse>;

/**
 * Body of the public `GET /system/ping` endpoint used by the renderer's
 * server-address connectivity test (see §7.2). Returns no privileged detail.
 */
export const SystemPingResponse = z.object({
  ok: z.literal(true),
  service: z.string().min(1),
  timestamp: z.string().min(1),
});
export type SystemPingResponse = z.infer<typeof SystemPingResponse>;
