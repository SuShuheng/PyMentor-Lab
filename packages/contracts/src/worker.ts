/**
 * Worker job envelope: the versioned JSON message FastAPI enqueues and the
 * LangGraph.js Worker consumes over Redis. Envelopes are idempotent by
 * `event_id` and replay-safe (see CONTRACT.md "Service and data contracts").
 *
 * Field names MUST stay in lock-step with `backend/app/contracts/worker.py`.
 */

import { z } from "zod";

/** Logical worker job kinds. The Worker emits proposals/events only; FastAPI
 *  remains the formal-state authority (see CONTRACT.md "Permissions"). */
export const WorkerJobKind = z.enum([
  "profile_diagnose",
  "path_recommend",
  "resource_generate",
  "coding_coach",
  "assessment_feedback",
  "tutoring_answer",
]);
export type WorkerJobKind = z.infer<typeof WorkerJobKind>;

/** Job lifecycle as known to FastAPI (the Worker reports progress separately). */
export const WorkerJobStatus = z.enum([
  "QUEUED",
  "RUNNING",
  "SUCCEEDED",
  "FAILED_RETRYABLE",
  "FAILED_FINAL",
  "CANCELLED",
]);
export type WorkerJobStatus = z.infer<typeof WorkerJobStatus>;

/**
 * The versioned envelope. `schema_version` gates consumer compatibility;
 * `event_id` is the idempotency key; `trace_id` threads observability.
 */
export const WorkerJobEnvelope = z.object({
  schema_version: z.literal(1),
  event_id: z.string().min(1),
  trace_id: z.string().min(1),
  tenant_id: z.string().min(1),
  student_id: z.string().min(1),
  kind: WorkerJobKind,
  /** Opaque, kind-specific payload validated by the consuming Agent node. */
  payload: z.record(z.string(), z.unknown()),
  /** ISO-8601 enqueue timestamp in UTC. */
  enqueued_at: z.string().min(1),
});
export type WorkerJobEnvelope = z.infer<typeof WorkerJobEnvelope>;
