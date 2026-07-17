import {
  AssessmentAgentInput,
  AssessmentAgentOutput,
  CoachAgentInput,
  CoachAgentOutput,
  OrchestratorAgentInput,
  OrchestratorAgentOutput,
  PathAgentInput,
  PathAgentOutput,
  ProfileAgentInput,
  ProfileAgentOutput,
  ResourceAgentInput,
  ResourceAgentOutput,
} from "@pymentor/contracts";
import type {
  AssessmentAgentInput as AssessmentInput,
  AssessmentAgentOutput as AssessmentOutput,
  CoachAgentInput as CoachInput,
  CoachAgentOutput as CoachOutput,
  OrchestratorAgentInput as OrchestratorInput,
  OrchestratorAgentOutput as OrchestratorOutput,
  PathAgentInput as PathInput,
  PathAgentOutput as PathOutput,
  ProfileAgentInput as ProfileInput,
  ProfileAgentOutput as ProfileOutput,
  ResourceAgentInput as ResourceInput,
  ResourceAgentOutput as ResourceOutput,
} from "@pymentor/contracts";

import {
  AGENT_TOOL_ALLOWLISTS,
  DEFAULT_AGENT_TIMEOUT_MS,
  FORBIDDEN_AGENT_PERMISSIONS,
} from "./policies.js";
import type { AgentNodeDefinition } from "./types.js";

function defineNode<TInput, TOutput>(
  definition: AgentNodeDefinition<TInput, TOutput>,
): Readonly<AgentNodeDefinition<TInput, TOutput>> {
  return Object.freeze(definition);
}

export const agentNodes = Object.freeze({
  orchestrator: defineNode<OrchestratorInput, OrchestratorOutput>({
    name: "orchestrator",
    inputSchema: OrchestratorAgentInput,
    outputSchema: OrchestratorAgentOutput,
    allowedTools: AGENT_TOOL_ALLOWLISTS.orchestrator,
    forbiddenPermissions: FORBIDDEN_AGENT_PERMISSIONS,
    timeoutMs: DEFAULT_AGENT_TIMEOUT_MS,
    fallback: () => ({
      route: "coach",
      intent_code: "SAFE_FALLBACK",
      summary: "The request needs a safe coaching response.",
    }),
  }),
  profile: defineNode<ProfileInput, ProfileOutput>({
    name: "profile",
    inputSchema: ProfileAgentInput,
    outputSchema: ProfileAgentOutput,
    allowedTools: AGENT_TOOL_ALLOWLISTS.profile,
    forbiddenPermissions: FORBIDDEN_AGENT_PERMISSIONS,
    timeoutMs: DEFAULT_AGENT_TIMEOUT_MS,
    fallback: () => ({
      kind: "profile_change",
      changes: [
        {
          dimension: "NEEDS_REVIEW",
          delta: 0,
          reason: "No reliable profile change could be inferred.",
        },
      ],
    }),
  }),
  path: defineNode<PathInput, PathOutput>({
    name: "path",
    inputSchema: PathAgentInput,
    outputSchema: PathAgentOutput,
    allowedTools: AGENT_TOOL_ALLOWLISTS.path,
    forbiddenPermissions: FORBIDDEN_AGENT_PERMISSIONS,
    timeoutMs: DEFAULT_AGENT_TIMEOUT_MS,
    fallback: (input) => ({
      kind: "path_plan",
      steps: [
        {
          node_id: input.candidate_node_ids[0]!,
          action: "REVIEW",
          reason: "Use the first validated candidate while planning is unavailable.",
        },
      ],
    }),
  }),
  resource: defineNode<ResourceInput, ResourceOutput>({
    name: "resource",
    inputSchema: ResourceAgentInput,
    outputSchema: ResourceAgentOutput,
    allowedTools: AGENT_TOOL_ALLOWLISTS.resource,
    forbiddenPermissions: FORBIDDEN_AGENT_PERMISSIONS,
    timeoutMs: DEFAULT_AGENT_TIMEOUT_MS,
    fallback: (input) => ({
      kind: "resource_request",
      requests: [
        {
          resource_type: input.resource_types[0]!,
          objective: "Provide a concise resource for the validated learning need.",
        },
      ],
    }),
  }),
  coach: defineNode<CoachInput, CoachOutput>({
    name: "coach",
    inputSchema: CoachAgentInput,
    outputSchema: CoachAgentOutput,
    allowedTools: AGENT_TOOL_ALLOWLISTS.coach,
    forbiddenPermissions: FORBIDDEN_AGENT_PERMISSIONS,
    timeoutMs: DEFAULT_AGENT_TIMEOUT_MS,
    fallback: () => ({
      kind: "coaching_feedback",
      diagnosis: "The coaching provider is temporarily unavailable.",
      hints: ["Review the latest failing example and isolate one small step."],
      next_test: "Run the smallest focused test again after that step.",
    }),
  }),
  assessment: defineNode<AssessmentInput, AssessmentOutput>({
    name: "assessment",
    inputSchema: AssessmentAgentInput,
    outputSchema: AssessmentAgentOutput,
    allowedTools: AGENT_TOOL_ALLOWLISTS.assessment,
    forbiddenPermissions: FORBIDDEN_AGENT_PERMISSIONS,
    timeoutMs: DEFAULT_AGENT_TIMEOUT_MS,
    fallback: (input) => ({
      kind: "assessment_feedback",
      rubric_scores: Object.fromEntries(input.rubric_keys.map((key) => [key, 0])),
      feedback: "Assessment is unavailable; no mastery should be inferred.",
      evidence_claims: [],
    }),
  }),
});
