/**
 * @pymentor/api-client public entrypoint.
 *
 * Re-exports the generated OpenAPI client. The generated sources under
 * ./generated are owned by openapi-ts and are excluded from tsc (see
 * tsconfig.json); their correctness is enforced by the freshness gate
 * (pnpm freshness) and the vitest suite. Renderers import from here.
 */

export * as generated from "./generated/index.js";
