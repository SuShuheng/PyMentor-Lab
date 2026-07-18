/**
 * Versioned FastAPI ↔ Agent Worker contracts.
 *
 * The Worker emits proposals, progress, and redacted audit events only. Formal
 * learning state remains owned by FastAPI. Field names stay in lock-step with
 * `backend/app/contracts/worker.py` and are checked by the conformance gate.
 */

import { z } from "zod";

const SAFE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const SAFE_CODE_PATTERN = /^[A-Z][A-Z0-9_]{0,63}$/;
const SHA256_PATTERN = /^[a-f0-9]{64}$/;

const SafeId = z.string().regex(SAFE_ID_PATTERN);
const SafeCode = z.string().regex(SAFE_CODE_PATTERN);
const Timestamp = z.string().datetime({ offset: true });
const Summary = z.string().min(1).max(8_000);
const ShortText = z.string().min(1).max(1_000);

export const WorkerJobKind = z.enum([
  "profile_diagnose",
  "path_recommend",
  "resource_generate",
  "coding_coach",
  "assessment_feedback",
  "tutoring_answer",
]);
export type WorkerJobKind = z.infer<typeof WorkerJobKind>;

export const WorkerJobStatus = z.enum([
  "QUEUED",
  "RUNNING",
  "SUCCEEDED",
  "FAILED_RETRYABLE",
  "FAILED_FINAL",
  "CANCELLED",
]);
export type WorkerJobStatus = z.infer<typeof WorkerJobStatus>;

export const AgentNodeName = z.enum([
  "orchestrator",
  "profile",
  "path",
  "resource",
  "coach",
  "assessment",
]);
export type AgentNodeName = z.infer<typeof AgentNodeName>;

export const SpecialistAgentNodeName = z.enum([
  "profile",
  "path",
  "resource",
  "coach",
  "assessment",
]);
export type SpecialistAgentNodeName = z.infer<typeof SpecialistAgentNodeName>;

export const AgentContext = z
  .object({
    course_id: SafeId.optional(),
    node_id: SafeId.optional(),
    task_id: SafeId.optional(),
    evidence_event_ids: z.array(SafeId).max(64),
  })
  .strict();
export type AgentContext = z.infer<typeof AgentContext>;

export const OrchestratorAgentInput = z
  .object({
    kind: WorkerJobKind,
    request: z.string().min(1).max(4_000),
    context: AgentContext,
  })
  .strict();
export type OrchestratorAgentInput = z.infer<typeof OrchestratorAgentInput>;

export const OrchestratorAgentOutput = z
  .object({
    route: SpecialistAgentNodeName,
    intent_code: SafeCode,
    summary: ShortText,
  })
  .strict();
export type OrchestratorAgentOutput = z.infer<typeof OrchestratorAgentOutput>;

export const ProfileAgentInput = z
  .object({
    evidence_summary: Summary,
    current_profile_version: z.number().int().positive(),
    context: AgentContext,
  })
  .strict();
export type ProfileAgentInput = z.infer<typeof ProfileAgentInput>;

const ProfileChange = z
  .object({
    dimension: SafeCode,
    delta: z.number().min(-1).max(1),
    reason: ShortText,
  })
  .strict();

export const ProfileAgentOutput = z
  .object({
    kind: z.literal("profile_change"),
    changes: z.array(ProfileChange).min(1).max(16),
  })
  .strict();
export type ProfileAgentOutput = z.infer<typeof ProfileAgentOutput>;

export const PathAgentInput = z
  .object({
    profile_summary: Summary,
    available_minutes: z.number().int().min(1).max(1_440),
    candidate_node_ids: z.array(SafeId).min(1).max(64),
    context: AgentContext,
  })
  .strict();
export type PathAgentInput = z.infer<typeof PathAgentInput>;

const PathStepProposal = z
  .object({
    node_id: SafeId,
    action: z.enum(["LEARN", "REMEDIATE", "REVIEW", "PRACTICE"]),
    reason: ShortText,
  })
  .strict();

export const PathAgentOutput = z
  .object({
    kind: z.literal("path_plan"),
    steps: z.array(PathStepProposal).min(1).max(32),
  })
  .strict();
export type PathAgentOutput = z.infer<typeof PathAgentOutput>;

export const LearningResourceType = z.enum([
  "MICRO_LECTURE",
  "STRUCTURE_CARD",
  "TRACE_ANIMATION",
  "LAYERED_EXERCISE",
  "NOTEBOOK_TASK",
]);
export type LearningResourceType = z.infer<typeof LearningResourceType>;

export const ResourceAgentInput = z
  .object({
    learning_need: Summary,
    resource_types: z.array(LearningResourceType).min(1).max(5),
    tutoring_question: z.string().min(1).max(4_000).optional(),
    context: AgentContext,
  })
  .strict();
export type ResourceAgentInput = z.infer<typeof ResourceAgentInput>;

const ResourceRequest = z
  .object({
    resource_type: LearningResourceType,
    objective: ShortText,
  })
  .strict();

export const ResourceAgentOutput = z
  .object({
    kind: z.literal("resource_request"),
    requests: z.array(ResourceRequest).min(1).max(5),
    answer: z.string().min(1).max(8_000).optional(),
  })
  .strict();
export type ResourceAgentOutput = z.infer<typeof ResourceAgentOutput>;

export const CoachAgentInput = z
  .object({
    error_summary: Summary,
    test_summary: Summary,
    hint_level: z.number().int().min(1).max(3),
    context: AgentContext,
  })
  .strict();
export type CoachAgentInput = z.infer<typeof CoachAgentInput>;

export const CoachAgentOutput = z
  .object({
    kind: z.literal("coaching_feedback"),
    diagnosis: Summary,
    hints: z.array(ShortText).min(1).max(3),
    next_test: ShortText,
  })
  .strict();
export type CoachAgentOutput = z.infer<typeof CoachAgentOutput>;

export const AssessmentAgentInput = z
  .object({
    response_summary: Summary,
    rubric_keys: z.array(SafeCode).min(1).max(16),
    context: AgentContext,
  })
  .strict();
export type AssessmentAgentInput = z.infer<typeof AssessmentAgentInput>;

export const AssessmentAgentOutput = z
  .object({
    kind: z.literal("assessment_feedback"),
    rubric_scores: z.record(SafeCode, z.number().min(0).max(1)),
    feedback: Summary,
    evidence_claims: z.array(ShortText).max(16),
  })
  .strict();
export type AssessmentAgentOutput = z.infer<typeof AssessmentAgentOutput>;

export const AgentProposal = z.discriminatedUnion("kind", [
  ProfileAgentOutput,
  PathAgentOutput,
  ResourceAgentOutput,
  CoachAgentOutput,
  AssessmentAgentOutput,
]);
export type AgentProposal = z.infer<typeof AgentProposal>;

export const WorkerJobEnvelope = z
  .object({
    schema_version: z.literal(1),
    event_id: SafeId,
    trace_id: SafeId,
    tenant_id: SafeId,
    student_id: SafeId,
    kind: WorkerJobKind,
    payload: z.record(z.string().max(64), z.unknown()),
    enqueued_at: Timestamp,
  })
  .strict();
export type WorkerJobEnvelope = z.infer<typeof WorkerJobEnvelope>;

export const AgentProposalEnvelope = z
  .object({
    schema_version: z.literal(1),
    agent_run_id: SafeId,
    event_id: SafeId,
    trace_id: SafeId,
    tenant_id: SafeId,
    student_id: SafeId,
    node: SpecialistAgentNodeName,
    status: z.enum(["SUCCEEDED", "FAILED_RETRYABLE", "FAILED_FINAL"]),
    proposal: AgentProposal.nullable(),
    error_code: SafeCode.optional(),
    fallback_used: z.boolean(),
    completed_at: Timestamp,
  })
  .strict()
  .superRefine((value, context) => {
    if (value.status === "SUCCEEDED" && value.proposal === null) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["proposal"],
        message: "successful Agent run requires a proposal",
      });
    }
    if (value.status === "SUCCEEDED") {
      if (value.error_code !== undefined) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["error_code"],
          message: "successful Agent run cannot include an error code",
        });
      }
      const expectedKind = {
        profile: "profile_change",
        path: "path_plan",
        resource: "resource_request",
        coach: "coaching_feedback",
        assessment: "assessment_feedback",
      } as const;
      if (value.proposal !== null && value.proposal.kind !== expectedKind[value.node]) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["proposal", "kind"],
          message: "proposal kind does not match producing Agent node",
        });
      }
    } else {
      if (value.proposal !== null) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["proposal"],
          message: "failed Agent run cannot include a proposal",
        });
      }
      if (value.error_code === undefined) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["error_code"],
          message: "failed Agent run requires an error code",
        });
      }
    }
  });
export type AgentProposalEnvelope = z.infer<typeof AgentProposalEnvelope>;

export const AgentAuditEventType = z.enum([
  "RUN_STARTED",
  "NODE_STARTED",
  "TOOL_STARTED",
  "TOOL_COMPLETED",
  "TOOL_FAILED",
  "NODE_COMPLETED",
  "NODE_FAILED",
  "CHECKPOINT_SAVED",
  "RUN_COMPLETED",
  "RUN_FAILED",
  "RUN_CANCELLED",
  "REPLAY_STARTED",
]);
export type AgentAuditEventType = z.infer<typeof AgentAuditEventType>;

export const AgentAuditDetail = z
  .object({
    status: WorkerJobStatus.optional(),
    code: SafeCode.optional(),
    latency_ms: z.number().int().nonnegative().max(3_600_000).optional(),
    input_bytes: z.number().int().nonnegative().max(1_048_576).optional(),
    output_bytes: z.number().int().nonnegative().max(1_048_576).optional(),
    argument_digest: z.string().regex(SHA256_PATTERN).optional(),
    result_digest: z.string().regex(SHA256_PATTERN).optional(),
    retry_count: z.number().int().min(0).max(10).optional(),
    fallback: z.boolean().optional(),
  })
  .strict();
export type AgentAuditDetail = z.infer<typeof AgentAuditDetail>;

export const AgentAuditEnvelope = z
  .object({
    schema_version: z.literal(1),
    agent_run_id: SafeId,
    event_id: SafeId,
    trace_id: SafeId,
    tenant_id: SafeId,
    student_id: SafeId,
    sequence: z.number().int().positive().max(1_000_000),
    event_type: AgentAuditEventType,
    node: AgentNodeName.optional(),
    tool_name: z.string().regex(SAFE_ID_PATTERN).optional(),
    checkpoint_id: SafeId.optional(),
    detail: AgentAuditDetail,
    occurred_at: Timestamp,
  })
  .strict();
export type AgentAuditEnvelope = z.infer<typeof AgentAuditEnvelope>;

export const AgentReplayRequest = z
  .object({
    schema_version: z.literal(1),
    tenant_id: SafeId,
    original_event_id: SafeId,
    replay_event_id: SafeId,
    checkpoint_id: SafeId,
    requested_at: Timestamp,
  })
  .strict()
  .superRefine((value, context) => {
    if (value.original_event_id === value.replay_event_id) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["replay_event_id"],
        message: "replay event identity must differ from the original",
      });
    }
  });
export type AgentReplayRequest = z.infer<typeof AgentReplayRequest>;
