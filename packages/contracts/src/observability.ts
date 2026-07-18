/** Strict BE-010 system observability contracts. */

import { z } from "zod";

import { ProviderType } from "./providers.js";

const Timestamp = z.string().datetime({ offset: true });
const PageMetadata = z
  .object({
    number: z.number().int().positive(),
    size: z.number().int().min(1).max(100),
    total_items: z.number().int().nonnegative(),
    total_pages: z.number().int().nonnegative(),
  })
  .strict();

const ComponentHealthView = z
  .object({
    component: z.string().min(1).max(32),
    status: z.enum(["HEALTHY", "DEGRADED"]),
    latency_ms: z.number().int().nonnegative(),
    detail: z.string().min(1).max(64),
  })
  .strict();

export const AdminSystemHealthView = z
  .object({
    status: z.enum(["HEALTHY", "DEGRADED"]),
    checked_at: Timestamp,
    components: z.array(ComponentHealthView),
  })
  .strict();
export type AdminSystemHealthView = z.infer<typeof AdminSystemHealthView>;

const ProviderMetricItem = z
  .object({
    provider_type: ProviderType,
    vendor: z.string(),
    model: z.string(),
    calls: z.number().int().nonnegative(),
    errors: z.number().int().nonnegative(),
    rate_limited: z.number().int().nonnegative(),
    average_latency_ms: z.number().nonnegative(),
    p95_latency_ms: z.number().int().nonnegative(),
    error_rate: z.number().min(0).max(1),
  })
  .strict();

export const ProviderMetricsView = z
  .object({
    since: Timestamp,
    until: Timestamp,
    items: z.array(ProviderMetricItem),
  })
  .strict();
export type ProviderMetricsView = z.infer<typeof ProviderMetricsView>;

const AdminLogItem = z
  .object({
    id: z.string().min(1).max(128),
    source: z.enum(["REQUEST", "AGENT", "AUDIT", "ERROR"]),
    level: z.string().min(1).max(16),
    message: z.string().min(1).max(255),
    trace_id: z.string().min(1).max(128),
    context: z.record(z.string(), z.unknown()),
    created_at: Timestamp,
  })
  .strict();

export const AdminLogPage = z
  .object({
    items: z.array(AdminLogItem),
    page: PageMetadata,
    truncated: z.boolean(),
  })
  .strict();
export type AdminLogPage = z.infer<typeof AdminLogPage>;
