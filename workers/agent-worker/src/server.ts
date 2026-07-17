/**
 * Worker HTTP entrypoint. Launches the health server.
 *
 * The real worker consumes Redis job envelopes (BE-006); this bootstrap server
 * only answers health probes so docker-compose healthchecks and the admin
 * health board can observe the process.
 */

import { serve } from "@hono/node-server";

import { buildHealthApp } from "./health.js";

const PORT = Number(process.env["PYMENTOR_WORKER_PORT"] ?? "8081");

const app = buildHealthApp();

serve({ fetch: app.fetch, port: PORT }, (info) => {
  // eslint-disable-next-line no-console
  console.log(`agent-worker listening on http://localhost:${info.port}`);
});
