/** Versioned student code-run and private sandbox-supervisor contracts. */

import { z } from "zod";

export const CodeRunMode = z.enum(["RUN", "TRACE", "SUBMIT"]);
export type CodeRunMode = z.infer<typeof CodeRunMode>;

export const CodeRunStatus = z.enum([
  "QUEUED",
  "RUNNING",
  "COMPLETED",
  "USER_ERROR",
  "PLATFORM_ERROR",
  "TIMEOUT",
  "CANCELLED",
]);
export type CodeRunStatus = z.infer<typeof CodeRunStatus>;

export const SandboxRunStatus = CodeRunStatus;
export type SandboxRunStatus = z.infer<typeof SandboxRunStatus>;

export const TestVisibility = z.enum(["VISIBLE", "HIDDEN"]);
export type TestVisibility = z.infer<typeof TestVisibility>;

export const SandboxComparison = z.enum(["EQUAL", "APPROX", "UNORDERED", "MATCHES"]);
export type SandboxComparison = z.infer<typeof SandboxComparison>;

export const SandboxEntrypointKind = z.enum(["FUNCTION", "SCRIPT"]);
export type SandboxEntrypointKind = z.infer<typeof SandboxEntrypointKind>;

export const SandboxPhase = z.enum(["VISIBLE", "HIDDEN"]);
export type SandboxPhase = z.infer<typeof SandboxPhase>;

export const SandboxEntrypoint = z
  .object({
    kind: SandboxEntrypointKind,
    name: z.string().min(1).max(128).nullish(),
  })
  .strict();
export type SandboxEntrypoint = z.infer<typeof SandboxEntrypoint>;

export const SandboxTestCase = z
  .object({
    id: z.string().min(1).max(128),
    args: z.array(z.unknown()).default([]),
    kwargs: z.record(z.string(), z.unknown()).default({}),
    expected: z.unknown().optional(),
    stdin: z.string().max(65_536).nullish(),
    expected_stdout: z.string().max(65_536).nullish(),
    comparison: SandboxComparison.default("EQUAL"),
    transfer: z.boolean().default(false),
  })
  .strict();
export type SandboxTestCase = z.infer<typeof SandboxTestCase>;

export const SandboxTaskTests = z
  .object({
    entrypoint: SandboxEntrypoint,
    allowed_imports: z.array(z.string()).max(32).default([]),
    visible: z.array(SandboxTestCase).max(256).default([]),
    hidden: z.array(SandboxTestCase).max(256).default([]),
  })
  .strict();
export type SandboxTaskTests = z.infer<typeof SandboxTaskTests>;

export const SandboxHint = z
  .object({
    key: z.string().min(1).max(128),
    level: z.number().int().min(1).max(3),
    content: z.string().min(1).max(8_192),
    independence_cost: z.number().min(0).max(100),
  })
  .strict();
export type SandboxHint = z.infer<typeof SandboxHint>;

export const SandboxHintPolicy = z
  .object({
    max_level: z.number().int().min(0).max(3),
    hints: z.array(SandboxHint).max(3).default([]),
  })
  .strict();
export type SandboxHintPolicy = z.infer<typeof SandboxHintPolicy>;

export const SandboxExecutionPolicy = z
  .object({
    timeout_ms: z.number().int().min(100).max(30_000),
    memory_mb: z.number().int().min(16).max(1_024),
    pids_limit: z.number().int().min(1).max(128),
    output_limit_bytes: z.number().int().min(1_024).max(1_048_576),
    test_limit: z.number().int().min(1).max(256),
    trace_frame_limit: z.number().int().min(1).max(1_000),
  })
  .strict();
export type SandboxExecutionPolicy = z.infer<typeof SandboxExecutionPolicy>;

export const SandboxTestCaseResult = z
  .object({
    case_id: z.string().min(1).max(128),
    display_name: z.string().min(1).max(256),
    visibility: TestVisibility,
    comparison: SandboxComparison,
    transfer: z.boolean(),
    passed: z.boolean(),
    message: z.string().nullable().default(null),
    stdout: z.string().default(""),
    stderr: z.string().default(""),
    stdout_truncated: z.boolean().default(false),
    stderr_truncated: z.boolean().default(false),
    duration_ms: z.number().int().nonnegative(),
  })
  .strict();
export type SandboxTestCaseResult = z.infer<typeof SandboxTestCaseResult>;

export const TraceFrame = z
  .object({
    sequence: z.number().int().positive(),
    line: z.number().int().positive(),
    event: z.enum(["call", "line", "return", "exception"]),
    func_name: z.string().min(1).max(256),
    locals: z.record(z.string(), z.string()).nullish(),
  })
  .strict();
export type TraceFrame = z.infer<typeof TraceFrame>;

export const SandboxResourceUsage = z
  .object({
    cpu_ms: z.number().int().nonnegative(),
    wall_ms: z.number().int().nonnegative(),
    peak_memory_kb: z.number().int().nonnegative().nullable(),
    exit_code: z.number().int().nullable(),
  })
  .strict();
export type SandboxResourceUsage = z.infer<typeof SandboxResourceUsage>;

export const SandboxResult = z
  .object({
    run_id: z.string().min(1),
    status: CodeRunStatus,
    passed: z.boolean(),
    stdout: z.string(),
    stderr: z.string(),
    tests: z.array(SandboxTestCaseResult).max(256),
    trace_frames: z.array(TraceFrame).max(1_000).nullable(),
    resource_usage: SandboxResourceUsage,
    stdout_truncated: z.boolean(),
    stderr_truncated: z.boolean(),
    trace_truncated: z.boolean(),
    user_error: z.string().nullable(),
    platform_error: z.string().nullable(),
  })
  .strict();
export type SandboxResult = z.infer<typeof SandboxResult>;

export const SandboxExecutionRequest = z
  .object({
    protocol_version: z.literal("1"),
    request_id: z.string().min(1).max(128),
    run_id: z.string().min(1).max(128),
    trace_id: z.string().min(1).max(128),
    source_code: z.string().min(1).max(65_536),
    entrypoint: SandboxEntrypoint,
    cases: z.array(SandboxTestCase).max(256),
    allowed_imports: z.array(z.string()).max(32),
    phase: SandboxPhase,
    policy: SandboxExecutionPolicy,
    trace_enabled: z.boolean(),
  })
  .strict();
export type SandboxExecutionRequest = z.infer<typeof SandboxExecutionRequest>;

export const SandboxExecutionResponse = z
  .object({
    protocol_version: z.literal("1"),
    request_id: z.string().min(1).max(128),
    run_id: z.string().min(1).max(128),
    result: SandboxResult,
  })
  .strict();
export type SandboxExecutionResponse = z.infer<typeof SandboxExecutionResponse>;

export const CodeRunRequest = z
  .object({
    task_instance_id: z.string().min(1),
    source_code: z.string().min(1).max(65_536),
    mode: z.enum(["RUN", "TRACE"]),
    expected_task_version: z.number().int().positive(),
    trace_enabled: z.boolean().default(false),
  })
  .strict();
export type CodeRunRequest = z.infer<typeof CodeRunRequest>;

export const CodeSubmissionRequest = z
  .object({
    task_instance_id: z.string().min(1),
    source_code: z.string().min(1).max(65_536),
    expected_task_version: z.number().int().positive(),
  })
  .strict();
export type CodeSubmissionRequest = z.infer<typeof CodeSubmissionRequest>;

export const CodeRevisionView = z
  .object({
    id: z.string().min(1),
    sequence: z.number().int().positive(),
    source_digest: z.string().length(64),
    created_at: z.string().min(1),
  })
  .strict();
export type CodeRevisionView = z.infer<typeof CodeRevisionView>;

export const CodeRunView = z
  .object({
    run_id: z.string().min(1),
    task_instance_id: z.string().min(1),
    mode: CodeRunMode,
    status: CodeRunStatus,
    version: z.number().int().positive(),
    revision: CodeRevisionView,
    result: SandboxResult.nullish(),
    evidence_event_id: z.string().min(1).nullish(),
    requested_at: z.string().min(1),
    started_at: z.string().min(1).nullish(),
    completed_at: z.string().min(1).nullish(),
  })
  .strict();
export type CodeRunView = z.infer<typeof CodeRunView>;

export const HintRequest = z
  .object({
    level: z.number().int().min(1).max(3),
    revision_id: z.string().min(1).nullish(),
    expected_task_version: z.number().int().positive(),
  })
  .strict();
export type HintRequest = z.infer<typeof HintRequest>;

export const HintUsageView = z
  .object({
    id: z.string().min(1),
    task_instance_id: z.string().min(1),
    revision_id: z.string().min(1).nullish(),
    sequence: z.number().int().positive(),
    hint_key: z.string().min(1).max(128),
    level: z.number().int().min(1).max(3),
    cost: z.number().nonnegative(),
    content: z.string().min(1).max(8_192),
    created_at: z.string().min(1),
  })
  .strict();
export type HintUsageView = z.infer<typeof HintUsageView>;
