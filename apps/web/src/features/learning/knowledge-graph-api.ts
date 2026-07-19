/**
 * FE-018 — typed wrapper for BE-021 `GET /api/v1/knowledge/graph`.
 *
 * The generated SDK (@pymentor/api-client) does not yet expose this route, so
 * we go through the shared `client` from the generated runtime and keep the
 * request/response types here — mirroring the FE-014 onboarding and FE-020
 * practice wrappers. When the OpenAPI generator picks the route up, this
 * wrapper can be retired in favour of the generated function without changing
 * call sites.
 *
 * Honesty contract (BE-021):
 * - The graph payload is read-only and student-scoped; the wrapper only ever
 *   calls `client.get`, never `client.post` — there is no way to mutate the
 *   graph from the browser.
 * - `mastery_status` is the *server's* per-node projection. The renderer MUST
 *   NOT recolor nodes from anything the browser guessed (e.g. today's clicks).
 * - `kind` on edges carries the dependency flavour (typically `PREREQUISITE`).
 *   The UI renders all edges as arrows; it does not interpret weights.
 */
import { client, type MasteryStatusContract } from "@pymentor/api-client";

/**
 * Status for a node as projected by the server. Mirrors the BE-021 contract
 * field, which in turn reuses the existing `MasteryStatusContract` enum from
 * the generated types (`UNSEEN | LEARNING | PASSED_WITH_HELP |
 * INITIAL_MASTERY | STABLE_MASTERY | REVIEW_REQUIRED`).
 */
export type KnowledgeMasteryStatus = MasteryStatusContract;

/**
 * A node in the knowledge graph. `chapter_id` is opaque — the renderer only
 * uses it as an optional grouping/hint label, never as a truth source.
 */
export type KnowledgeGraphNode = {
  node_id: string;
  title: string;
  chapter_id: string;
  mastery_status: KnowledgeMasteryStatus;
};

/**
 * A directed edge in the knowledge graph. `kind` is the dependency flavour
 * (e.g. `PREREQUISITE`). The UI renders every edge as a single arrow; weights
 * are not part of the V1.1 contract.
 */
export type KnowledgeGraphEdge = {
  from_node_id: string;
  to_node_id: string;
  kind: string;
};

/** Response body for `GET /api/v1/knowledge/graph`. */
export type KnowledgeGraph = {
  course_id: string;
  nodes: ReadonlyArray<KnowledgeGraphNode>;
  edges: ReadonlyArray<KnowledgeGraphEdge>;
};

export type KnowledgeGraphOptions = {
  headers: { Authorization: string };
};

/**
 * Fetch the student's knowledge graph (nodes + prerequisite edges).
 *
 * Mirrors the generated SDK's `{ data, error, response }` result shape so
 * callers can use the same error-handling idiom as the generated endpoints.
 * The endpoint is read-only so no idempotency key is required.
 */
export async function getKnowledgeGraph({ headers }: KnowledgeGraphOptions) {
  return client.get<KnowledgeGraph, unknown, false>({
    url: "/api/v1/knowledge/graph",
    headers,
  });
}
