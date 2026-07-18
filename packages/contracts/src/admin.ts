/** Strict BE-010 administrative read contracts. */

import { z } from "zod";

const Timestamp = z.string().datetime({ offset: true });
const Uuid = z.string().uuid();
const Digest = z.string().regex(/^[0-9a-f]{64}$/);

const PageMetadata = z
  .object({
    number: z.number().int().min(1),
    size: z.number().int().min(1).max(100),
    total_items: z.number().int().nonnegative(),
    total_pages: z.number().int().nonnegative(),
  })
  .strict();

const AdminStudentSummary = z
  .object({
    id: Uuid,
    email: z.string().min(3).max(255),
    student_no: z.string().max(64).nullable(),
    display_name: z.string().max(128).nullable(),
    status: z.string().min(1).max(32),
    created_at: Timestamp,
    profile_version: z.number().int().nonnegative(),
    completed_tasks: z.number().int().nonnegative(),
    due_reviews: z.number().int().nonnegative(),
  })
  .strict();

export const AdminStudentPage = z
  .object({
    items: z.array(AdminStudentSummary),
    page: PageMetadata,
  })
  .strict();
export type AdminStudentPage = z.infer<typeof AdminStudentPage>;

const AdminProfileDimension = z
  .object({
    dimension: z.string().min(1).max(32),
    scope_key: z.string().min(1).max(128),
    score: z.number().min(0).max(1),
    confidence: z.number().min(0).max(1),
    support_level: z.number().int().min(0).max(3),
  })
  .strict();

export const AdminStudentProfile = z
  .object({
    student_id: Uuid,
    version: z.number().int().nonnegative(),
    dimensions: z.array(AdminProfileDimension),
    created_at: Timestamp.nullable(),
  })
  .strict();
export type AdminStudentProfile = z.infer<typeof AdminStudentProfile>;

export const AdminStudentProgress = z
  .object({
    student_id: Uuid,
    current_path_id: Uuid.nullable(),
    current_node_id: Uuid.nullable(),
    completed_tasks: z.number().int().nonnegative(),
    due_reviews: z.number().int().nonnegative(),
    mastery_counts: z.record(z.string().min(1).max(32), z.number().int().nonnegative()),
    last_active_at: Timestamp.nullable(),
  })
  .strict();
export type AdminStudentProgress = z.infer<typeof AdminStudentProgress>;

const AdminEvidenceItem = z
  .object({
    id: Uuid,
    event_id: z.string().min(1).max(128),
    event_type: z.string().min(1).max(64),
    course_id: Uuid.nullable(),
    node_id: Uuid.nullable(),
    task_id: Uuid.nullable(),
    trace_id: z.string().min(1).max(128),
    evidence_confidence: z.number().min(0).max(1),
    created_at: Timestamp,
  })
  .strict();

export const AdminEvidencePage = z
  .object({
    items: z.array(AdminEvidenceItem),
    page: PageMetadata,
  })
  .strict();
export type AdminEvidencePage = z.infer<typeof AdminEvidencePage>;

export const AdminMasterySummary = z
  .object({
    course_id: Uuid.nullable(),
    total_states: z.number().int().nonnegative(),
    counts: z.record(z.string().min(1).max(32), z.number().int().nonnegative()),
    due_reviews: z.number().int().nonnegative(),
    stable_ratio: z.number().min(0).max(1),
  })
  .strict();
export type AdminMasterySummary = z.infer<typeof AdminMasterySummary>;

const AdminResourceGateReview = z
  .object({
    gate: z.string().min(1).max(16),
    version: z.number().int().positive(),
    passed: z.boolean(),
    findings: z.array(z.string()),
    reviewer: z.string().min(1).max(128),
    created_at: Timestamp,
  })
  .strict();

const AdminResourceReviewItem = z
  .object({
    resource_id: Uuid,
    job_id: Uuid,
    student_id: Uuid,
    resource_type: z.string().min(1).max(32),
    version: z.number().int().positive(),
    status: z.string().min(1).max(32),
    content_digest: Digest,
    created_at: Timestamp,
    gates: z.array(AdminResourceGateReview),
  })
  .strict();

export const AdminResourceReviewPage = z
  .object({
    items: z.array(AdminResourceReviewItem),
    page: PageMetadata,
  })
  .strict();
export type AdminResourceReviewPage = z.infer<typeof AdminResourceReviewPage>;

const AdminAgentToolCall = z
  .object({
    sequence: z.number().int().positive(),
    node: z.string().max(32).nullable(),
    tool_name: z.string().min(1).max(128),
    event_type: z.string().min(1).max(32),
    status: z.string().max(32).nullable(),
    argument_digest: Digest.nullable(),
    result_digest: Digest.nullable(),
    latency_ms: z.number().int().nonnegative(),
    retry_count: z.number().int().nonnegative(),
    error_code: z.string().max(64).nullable(),
    occurred_at: Timestamp,
  })
  .strict();

export const AdminAgentRunView = z
  .object({
    external_run_id: z.string().min(1).max(128),
    event_id: z.string().min(1).max(128),
    trace_id: z.string().min(1).max(128),
    student_id: Uuid,
    status: z.string().min(1).max(32),
    route: z.string().max(32).nullable(),
    latest_sequence: z.number().int().nonnegative(),
    checkpoint_thread_id: z.string().max(128).nullable(),
    latest_checkpoint_id: z.string().max(128).nullable(),
    fallback_used: z.boolean(),
    error_code: z.string().max(64).nullable(),
    input_snapshot: z.record(z.string(), z.unknown()),
    output_snapshot: z.record(z.string(), z.unknown()),
    started_at: Timestamp.nullable(),
    completed_at: Timestamp.nullable(),
    created_at: Timestamp,
    tool_calls: z.array(AdminAgentToolCall),
  })
  .strict();
export type AdminAgentRunView = z.infer<typeof AdminAgentRunView>;
