/**
 * Sandbox result contract: the bounded, serializable outcome of running
 * student Python under strict isolation.
 *
 * The platform-error vs user-error split is critical — platform failures MUST
 * never reduce a student's ability/mastery (see PRD REQ-P0-007).
 * Field names MUST stay in lock-step with `backend/app/contracts/sandbox.py`.
 */

import { z } from "zod";

/** Lifecycle of a sandbox run. */
export const SandboxRunStatus = z.enum([
  "PASSED",
  "FAILED",
  "ERROR",
  "TIMEOUT",
  "CANCELLED",
]);
export type SandboxRunStatus = z.infer<typeof SandboxRunStatus>;

/**
 * One test case result inside a bounded run. Visible and hidden tests share
 * this shape; visibility is a property of the task policy, not the result.
 */
export const SandboxTestCaseResult = z.object({
  name: z.string().min(1),
  passed: z.boolean(),
  message: z.string().optional(),
  stdout: z.string().optional(),
  stderr: z.string().optional(),
  /** Wall-clock duration in milliseconds, capped by run policy. */
  duration_ms: z.number().int().nonnegative(),
});
export type SandboxTestCaseResult = z.infer<typeof SandboxTestCaseResult>;

/** A deterministic code-trace frame emitted by AST instrumentation. */
export const TraceFrame = z.object({
  line: z.number().int().positive(),
  event: z.enum(["call", "line", "return", "exception"]),
  func_name: z.string().min(1),
  /** Stringified locals, allowlisted and size-bounded by the runner. */
  locals: z.record(z.string(), z.string()).optional(),
});
export type TraceFrame = z.infer<typeof TraceFrame>;

/**
 * The bounded sandbox result. All fields are size-capped by the runner;
 * `platform_error` is set only when the runner/infrastructure failed and is
 * always separated from `user_error` (student code/test failure).
 */
export const SandboxResult = z.object({
  run_id: z.string().min(1),
  status: SandboxRunStatus,
  /** Student-facing exit summary (passed/failed/errored). */
  passed: z.boolean(),
  stdout: z.string(),
  stderr: z.string(),
  tests: z.array(SandboxTestCaseResult),
  trace: z.array(TraceFrame).optional(),
  /** Total bounded wall-clock duration in milliseconds. */
  duration_ms: z.number().int().nonnegative(),
  /** Bounded peak memory in kilobytes, or null if unmeasured. */
  peak_memory_kb: z.number().int().nonnegative().nullable(),
  /** Student code/test failure detail (safe to show and to record). */
  user_error: z.string().nullable(),
  /** Runner/infrastructure failure detail (never reduces mastery). */
  platform_error: z.string().nullable(),
});
export type SandboxResult = z.infer<typeof SandboxResult>;
