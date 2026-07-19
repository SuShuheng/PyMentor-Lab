/**
 * Stable, serializable error contract shared by FastAPI, Worker, Sandbox,
 * Electron main/preload, and the generated API client.
 *
 * See CONTRACT.md "Errors" section for the authoritative code table.
 * Field names MUST stay in lock-step with `backend/app/contracts/errors.py`.
 */

import { z } from "zod";

/**
 * The full set of stable error codes. Adding a code is a contract change that
 * requires a Pydantic ↔ Zod conformance update; codes are never renamed.
 */
export const ErrorCode = z.enum([
  "VALIDATION_ERROR",
  "AUTH_REQUIRED",
  "FORBIDDEN",
  "NOT_FOUND",
  "CONFLICT",
  "RATE_LIMITED",
  "PROVIDER_UNAVAILABLE",
  "CONTENT_REJECTED",
  "SANDBOX_USER_ERROR",
  "SANDBOX_PLATFORM_ERROR",
  "TIMEOUT",
  "CANCELLED",
  "INTERNAL_ERROR",
  "IPC_INVALID_SENDER",
  "IPC_CAPABILITY_DENIED",
]);
export type ErrorCode = z.infer<typeof ErrorCode>;

/** A single field-level validation problem, safe to bind to a form field. */
export const FieldError = z.object({
  field: z.string().min(1),
  code: z.string().min(1),
  message: z.string().min(1),
}).strict();
export type FieldError = z.infer<typeof FieldError>;

/**
 * The wire error envelope. `details` is an allowlisted object and MUST NOT
 * carry secrets, raw prompts, stack traces, database keys, or local paths.
 */
export const ErrorEnvelope = z.object({
  code: ErrorCode,
  message: z.string().min(1),
  trace_id: z.string().min(1),
  retryable: z.boolean(),
  field_errors: z.array(FieldError).optional(),
  details: z.record(z.string(), z.unknown()).optional(),
}).strict();
export type ErrorEnvelope = z.infer<typeof ErrorEnvelope>;
