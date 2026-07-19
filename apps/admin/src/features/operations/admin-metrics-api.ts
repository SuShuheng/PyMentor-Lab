import { client } from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";
import {
  MASTERY_STATUS_LABELS,
  MASTERY_STATUSES,
  type AgentTimelinePoint,
  type ApiUsageBucket,
  type MasteryStatus,
} from "@pymentor/charts";

/**
 * Advanced operations metrics served by BE-028
 * `GET /api/v1/admin/metrics?since=&until=&node_id=&course_id=`.
 *
 * The generated API client (`@pymentor/api-client`) does not yet expose this
 * endpoint because BE-028 lives on the backend branch and has not been merged
 * to `main`, so the OpenAPI regeneration has not picked it up. Until that
 * happens we call the endpoint through the same hey-api `client` instance the
 * generated SDK uses, which keeps authentication, base URL and `fetch`
 * configuration identical to every other admin call — the same escape hatch
 * FE-013 used for `GET /api/v1/admin/overview`.
 *
 * This module is intentionally generic over the BE-028 payload shape so that
 * sibling FE-026 (resource stats) can reuse the same fetcher and types without
 * forking the wrapper. The shared chart-input types (`ApiUsageBucket`,
 * `AgentTimelinePoint`, `MasteryStatus`) live in `@pymentor/charts` so the
 * chart components stay decoupled from this fetcher.
 */

export {
  MASTERY_STATUS_LABELS,
  MASTERY_STATUSES,
  type AgentTimelinePoint,
  type ApiUsageBucket,
  type MasteryStatus,
};

/** Aggregation window metadata returned by BE-028. */
export type MetricsWindow = {
  bucket: string;
  bucket_count: number;
  since: string;
  until: string;
};

export type ApiUsageMetrics = {
  buckets: ApiUsageBucket[];
};

export type MasteryDistribution = {
  counts: Partial<Record<MasteryStatus, number>>;
};

export type AgentTimeline = {
  points: AgentTimelinePoint[];
};

export const RESOURCE_TYPES = [
  "MICRO_LECTURE",
  "STRUCTURE_CARD",
  "LAYERED_EXERCISE",
  "NOTEBOOK_TASK",
  "TRACE_ANIMATION",
] as const;

export type ResourceType = (typeof RESOURCE_TYPES)[number];

/**
 * Per-type resource generation aggregate consumed by FE-026. BE-028 returns one
 * entry per `ResourceType` (defined in `backend/app/resources.py`) so the UI
 * can render count + success-rate gauge + avg-generation sparkline without
 * client-side grouping.
 */
export type ResourceStatItem = {
  resource_type: ResourceType;
  /** Total generation attempts in the window. */
  total: number;
  /** Attempts that reached a published / successful terminal state. */
  succeeded: number;
  /** `succeeded / total`, clamped to `[0, 1]`. */
  success_rate: number;
  /** Mean wall-clock generation time in milliseconds. */
  avg_generation_ms: number;
};

export type ResourceStats = {
  /** Course scope the backend enforced for this aggregation (null = tenant). */
  course_id?: string | null;
  since?: string;
  until?: string;
  /** Detailed per-type breakdown rendered by FE-026's stats panel. */
  items?: ResourceStatItem[];
};

/** Full BE-028 response payload. `resource_stats` is optional so FE-026 can
 * extend the same fetcher without breaking FE-025 callers that ignore it. */
export type AdminMetrics = {
  window: MetricsWindow;
  api_usage: ApiUsageMetrics;
  mastery_distribution: MasteryDistribution;
  agent_timeline: AgentTimeline;
  resource_stats?: ResourceStats;
};

export type AdminMetricsQuery = {
  accessToken: string;
  since?: string;
  until?: string;
  nodeId?: string;
  courseId?: string;
};

export function configureAdminMetricsClient(): void {
  client.setConfig({
    baseUrl: readServerUrl(),
    credentials: "include",
    fetch,
  });
}

function buildSearchParams(query: AdminMetricsQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (query.since) params.set("since", query.since);
  if (query.until) params.set("until", query.until);
  if (query.nodeId) params.set("node_id", query.nodeId);
  if (query.courseId) params.set("course_id", query.courseId);
  return params;
}

export async function fetchAdminMetrics({
  accessToken,
  ...filters
}: AdminMetricsQuery): Promise<AdminMetrics> {
  configureAdminMetricsClient();
  const params = buildSearchParams({ accessToken, ...filters });
  const queryString = params.toString();
  const url = `/api/v1/admin/metrics${queryString ? `?${queryString}` : ""}`;
  const { data, error, response } = await client.get<AdminMetrics>({
    headers: { Authorization: `Bearer ${accessToken}` },
    url,
  });
  if (!response.ok || !data) {
    const detail = error && typeof error === "object" ? Reflect.get(error, "detail") : undefined;
    throw new Error(typeof detail === "string" ? detail : "管理指标数据暂时不可用，请稍后重试");
  }
  return data;
}
