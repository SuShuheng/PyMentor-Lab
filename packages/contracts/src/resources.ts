/** Versioned BE-007 resource-job contracts shared by API, Worker, and UI. */

import { z } from "zod";

export const ResourceTypeContract = z.enum([
  "MICRO_LECTURE",
  "STRUCTURE_CARD",
  "TRACE_ANIMATION",
  "LAYERED_EXERCISE",
  "NOTEBOOK_TASK",
]);
export type ResourceTypeContract = z.infer<typeof ResourceTypeContract>;

export const ResourceJobStatusContract = z.enum([
  "QUEUED",
  "VALIDATING",
  "GENERATING",
  "PARTIAL_READY",
  "REVIEWING",
  "READY",
  "FAILED_RETRYABLE",
  "FAILED_FINAL",
  "CANCELLED",
]);
export type ResourceJobStatusContract = z.infer<typeof ResourceJobStatusContract>;

export const ResourceArtifactStatusContract = z.enum([
  "STAGED",
  "REVIEWING",
  "PUBLISHED",
  "REJECTED",
]);
export type ResourceArtifactStatusContract = z.infer<typeof ResourceArtifactStatusContract>;

export const ResourceJobCreate = z.object({
  course_id: z.string().uuid(),
  node_id: z.string().uuid(),
  resource_types: z
    .array(ResourceTypeContract)
    .min(1)
    .max(5)
    .refine((items) => new Set(items).size === items.length, "resource types must be unique"),
});
export type ResourceJobCreate = z.infer<typeof ResourceJobCreate>;

export const ResourceObjectView = z.object({
  object_key: z.string().min(1),
  digest: z.string().regex(/^[a-f0-9]{64}$/),
  mime_type: z.string().min(1),
  size_bytes: z.number().int().nonnegative(),
  version: z.number().int().positive(),
  published: z.boolean(),
});
export type ResourceObjectView = z.infer<typeof ResourceObjectView>;

export const ResourceArtifactView = z.object({
  id: z.string().uuid(),
  resource_type: ResourceTypeContract,
  version: z.number().int().positive(),
  status: ResourceArtifactStatusContract,
  source_ids: z.array(z.string().uuid()).min(1),
  context_digest: z.string().regex(/^[a-f0-9]{64}$/),
  content_digest: z.string().regex(/^[a-f0-9]{64}$/),
  object: ResourceObjectView.nullable(),
  published_at: z.string().nullable(),
});
export type ResourceArtifactView = z.infer<typeof ResourceArtifactView>;

export const ResourceJobView = z.object({
  id: z.string().uuid(),
  course_id: z.string().uuid(),
  node_id: z.string().uuid(),
  status: ResourceJobStatusContract,
  progress_percent: z.number().int().min(0).max(100),
  requested_types: z.array(ResourceTypeContract).min(1).max(5),
  artifacts: z.array(ResourceArtifactView),
  created_at: z.string().min(1),
  updated_at: z.string().min(1),
});
export type ResourceJobView = z.infer<typeof ResourceJobView>;
