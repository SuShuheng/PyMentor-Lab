/**
 * @pymentor/api-client public entrypoint.
 *
 * Re-exports the generated OpenAPI SDK and its configured fetch client.
 * Generated sources under ./generated remain owned by openapi-ts; they are
 * type-checked through this entrypoint and guarded by the freshness suite.
 * Renderers import only from this public module.
 */

export { client } from "./generated/client.gen.js";
export * from "./generated/index.js";
