/**
 * BE-028 advanced-metrics payload types shared by the chart components.
 *
 * These mirror the `GET /api/v1/admin/metrics` response shape so the chart
 * components in `@pymentor/charts` can stay decoupled from the admin app's API
 * wrapper. The admin wrapper (`admin-metrics-api.ts`) imports these types and
 * adds the fetcher, so FE-026 (resource stats) can extend the same payload
 * without forking the chart inputs.
 */

/** The six mastery statuses defined in `MasteryStatusContract`. */
export const MASTERY_STATUSES = [
  "UNSEEN",
  "LEARNING",
  "PASSED_WITH_HELP",
  "INITIAL_MASTERY",
  "STABLE_MASTERY",
  "REVIEW_REQUIRED",
] as const;

export type MasteryStatus = (typeof MASTERY_STATUSES)[number];

/** A single API-usage time bucket. `p50`/`p95` are `null` on empty buckets. */
export type ApiUsageBucket = {
  bucket_start: string;
  total: number;
  p50: number | null;
  p95: number | null;
  error_rate: number;
  throttle_rate: number;
};

/** A point on the agent execution timeline (Gantt-style). */
export type AgentTimelinePoint = {
  run_id: string;
  student_id: string | null;
  route: string;
  status: string;
  fallback: boolean;
  started_at: string;
  ended_at: string | null;
  latency_ms: number | null;
};
