/**
 * Worker health check, built on the shared HealthResponse contract.
 *
 * The worker is the LangGraph.js process (six-agent orchestration); at the
 * bootstrap stage it only proves it consumes the frozen contract and answers
 * `/health`. The six nodes, queue consumption, and provider injection land in
 * BE-006.
 */

import { Hono } from "hono";

import { HealthResponse, type HealthResponse as HealthResponseType } from "@pymentor/contracts";

const SERVICE_NAME = "agent-worker";
const SERVICE_VERSION = process.env["PYMENTOR_SERVICE_VERSION"] ?? "0.0.0";

export interface NowProvider {
  now(): string;
}

export interface ReadinessProvider {
  isReady(): boolean;
}

const isoNow = (): string => new Date().toISOString();

/**
 * Build the health sub-app. `now` is injectable so tests can assert the
 * contract deterministically without depending on wall-clock time.
 */
export function buildHealthApp(
  now: NowProvider = { now: isoNow },
  readiness: ReadinessProvider = { isReady: () => false },
  resourceGeneration?: (context: import("hono").Context) => Response | Promise<Response>,
): Hono {
  const app = new Hono();

  app.get("/health", (c) => {
    const body: HealthResponseType = {
      status: "ok",
      service: SERVICE_NAME,
      version: SERVICE_VERSION,
      timestamp: now.now(),
    };
    // Validate our own response against the shared contract.
    const parsed = HealthResponse.safeParse(body);
    if (!parsed.success) {
      return c.json({ status: "down", service: SERVICE_NAME }, 500);
    }
    return c.json(parsed.data, 200);
  });

  app.get("/ready", (c) => {
    if (!readiness.isReady()) {
      return c.json({ status: "not_ready", service: SERVICE_NAME }, 503);
    }
    return c.json({ status: "ready", service: SERVICE_NAME }, 200);
  });

  if (resourceGeneration) {
    app.post("/internal/v1/resource-generation", resourceGeneration);
  }

  return app;
}
