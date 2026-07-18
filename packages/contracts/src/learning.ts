/** Deterministic learning-loop contracts. Mirrors backend Pydantic models. */

import { z } from "zod";

export const ProfileDimension = z.enum([
  "CONCEPT_KNOWLEDGE",
  "EXECUTION_MODEL",
  "IMPLEMENTATION",
  "DECOMPOSITION",
  "DEBUGGING",
  "TESTING",
  "TRANSFER",
  "INDEPENDENCE_SUPPORT",
]);

export const LearningPathStatus = z.enum(["CURRENT", "SUPERSEDED"]);
export const PathStepKind = z.enum(["REVIEW", "LEARN", "PRACTICE", "ASSESSMENT"]);
export const PathValidationStatus = z.enum(["VALIDATED", "REPAIRED", "FALLBACK"]);
export const TaskInstanceStatus = z.enum([
  "ACTIVE",
  "SUBMITTED",
  "COMPLETED",
  "CANCELLED",
]);
export const MasteryStatus = z.enum([
  "UNSEEN",
  "LEARNING",
  "PASSED_WITH_HELP",
  "INITIAL_MASTERY",
  "STABLE_MASTERY",
  "REVIEW_REQUIRED",
]);
export const ReviewStatus = z.enum(["SCHEDULED", "DUE", "COMPLETED", "CANCELLED"]);

export const ProfileDimensionView = z.object({
  dimension: ProfileDimension,
  scope_key: z.string().min(1).max(128),
  score: z.number().min(0).max(1),
  confidence: z.number().min(0).max(1),
  support_level: z.number().int().min(0).max(3),
});
export type ProfileDimensionView = z.infer<typeof ProfileDimensionView>;

export const ProfileSnapshot = z.object({
  student_id: z.string().min(1),
  version: z.number().int().min(1),
  source_event_id: z.string().min(1),
  dimensions: z.array(ProfileDimensionView),
});
export type ProfileSnapshot = z.infer<typeof ProfileSnapshot>;

export const ProfileDisputeRequest = z.object({
  profile_version_id: z.string().min(1),
  reason: z.string().min(1).max(2000),
});
export type ProfileDisputeRequest = z.infer<typeof ProfileDisputeRequest>;

export const ProfileDisputeView = z.object({
  id: z.string().min(1),
  profile_version_id: z.string().min(1),
  reason: z.string().min(1).max(2000),
});
export type ProfileDisputeView = z.infer<typeof ProfileDisputeView>;

export const PathStepView = z.object({
  id: z.string().min(1),
  position: z.number().int().min(1),
  node_id: z.string().min(1),
  kind: PathStepKind,
  estimated_minutes: z.number().int().min(1),
  scenario_key: z.string().min(1).max(128),
  validation_status: PathValidationStatus,
});
export type PathStepView = z.infer<typeof PathStepView>;

export const PathSnapshot = z.object({
  id: z.string().min(1),
  course_id: z.string().min(1),
  version: z.number().int().min(1),
  status: LearningPathStatus,
  steps: z.array(PathStepView),
});
export type PathSnapshot = z.infer<typeof PathSnapshot>;

export const TodayItem = z.object({
  id: z.string().min(1),
  course_id: z.string().min(1),
  node_id: z.string().min(1),
  kind: PathStepKind,
  estimated_minutes: z.number().int().min(1),
  due_at: z.string().nullish(),
  task_version_id: z.string().nullish(),
});
export type TodayItem = z.infer<typeof TodayItem>;

export const TaskStartResponse = z.object({
  id: z.string().min(1),
  task_version_id: z.string().min(1),
  status: TaskInstanceStatus,
  snapshot: z.record(z.string(), z.unknown()),
  started_at: z.string().min(1),
  version: z.number().int().min(1),
});
export type TaskStartResponse = z.infer<typeof TaskStartResponse>;

export const AssessmentSubmission = z.object({
  evidence_event_id: z.string().min(1).max(128),
  expected_task_version: z.number().int().min(1),
});
export type AssessmentSubmission = z.infer<typeof AssessmentSubmission>;

export const TaskSubmissionResponse = z.object({
  assessment_id: z.string().min(1),
  task_instance_id: z.string().min(1),
  course_id: z.string().min(1),
  node_id: z.string().min(1),
  status: z.union([MasteryStatus, z.literal("PLATFORM_ERROR")]),
  version: z.number().int().min(0),
  review_due_at: z.string().nullish(),
});
export type TaskSubmissionResponse = z.infer<typeof TaskSubmissionResponse>;

export const MasteryView = z.object({
  id: z.string().min(1),
  course_id: z.string().min(1),
  node_id: z.string().min(1),
  status: MasteryStatus,
  version: z.number().int().min(1),
  review_due_at: z.string().nullish(),
});
export type MasteryView = z.infer<typeof MasteryView>;

export const ReviewView = z.object({
  id: z.string().min(1),
  course_id: z.string().min(1),
  node_id: z.string().min(1),
  scenario_key: z.string().min(1).max(128),
  due_at: z.string().min(1),
  status: ReviewStatus,
  reschedule_count: z.number().int().min(0),
  version: z.number().int().min(1),
});
export type ReviewView = z.infer<typeof ReviewView>;

export const ReviewRescheduleRequest = z.object({
  due_at: z.string().min(1),
  expected_version: z.number().int().min(1),
});
export type ReviewRescheduleRequest = z.infer<typeof ReviewRescheduleRequest>;
