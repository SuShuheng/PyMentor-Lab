export const FORBIDDEN_AGENT_PERMISSIONS = Object.freeze([
  "formal_state.write",
  "filesystem.access",
  "shell.execute",
  "provider.secret.read",
] as const);

export const AGENT_TOOL_ALLOWLISTS = Object.freeze({
  orchestrator: Object.freeze(["llm.complete"]),
  profile: Object.freeze(["evidence.read", "llm.complete"]),
  path: Object.freeze(["profile.read", "course.read", "llm.complete"]),
  resource: Object.freeze(["knowledge.search", "llm.complete", "image.generate"]),
  coach: Object.freeze(["sandbox.evidence.read", "llm.complete"]),
  assessment: Object.freeze(["evidence.read", "llm.complete"]),
} as const);

export const DEFAULT_AGENT_TIMEOUT_MS = 30_000;

export const EXPECTED_ROUTE_BY_KIND = Object.freeze({
  profile_diagnose: "profile",
  path_recommend: "path",
  resource_generate: "resource",
  tutoring_answer: "resource",
  coding_coach: "coach",
  assessment_feedback: "assessment",
}) satisfies Readonly<Record<WorkerJobKind, SpecialistAgentNodeName>>;
import type { SpecialistAgentNodeName, WorkerJobKind } from "@pymentor/contracts";
