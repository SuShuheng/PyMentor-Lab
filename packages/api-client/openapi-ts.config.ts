import { defineConfig } from "@hey-api/openapi-ts";

/**
 * openapi-ts generation config.
 *
 * Input:  openapi.json (exported from the FastAPI app by scripts/export_openapi.py)
 * Output: src/generated/ — the committed, generated TypeScript SDK.
 *
 * The freshness gate (`pnpm freshness`) regenerates and fails if the committed
 * output differs, catching stale clients before merge (frozen design §18.1:
 * "OpenAPI SDK diff").
 */
export default defineConfig({
  input: "openapi.json",
  output: {
    path: "src/generated",
    clean: true,
  },
  plugins: [
    // Runtime base URL is configured by the renderer (server-address input).
    "@hey-api/client-fetch",
    "@hey-api/typescript",
  ],
});
