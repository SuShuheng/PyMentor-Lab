import { Annotation } from "@langchain/langgraph";
import type {
  AgentNodeName,
  AgentProposal,
  SpecialistAgentNodeName,
  WorkerJobEnvelope,
} from "@pymentor/contracts";

export const AgentWorkflowState = Annotation.Root({
  job: Annotation<WorkerJobEnvelope>(),
  route: Annotation<SpecialistAgentNodeName | null>({
    reducer: (_current, update) => update,
    default: () => null,
  }),
  executedNodes: Annotation<AgentNodeName[], AgentNodeName[]>({
    reducer: (current, update) => current.concat(update),
    default: () => [],
  }),
  proposal: Annotation<AgentProposal | null>({
    reducer: (_current, update) => update,
    default: () => null,
  }),
  auditSequence: Annotation<number>({
    reducer: (_current, update) => update,
    default: () => 0,
  }),
  fallbackUsed: Annotation<boolean>({
    reducer: (current, update) => current || update,
    default: () => false,
  }),
  terminalFailure: Annotation<string | null>({
    reducer: (_current, update) => update,
    default: () => null,
  }),
});

export type AgentWorkflowStateValue = typeof AgentWorkflowState.State;
export type AgentWorkflowStateUpdate = typeof AgentWorkflowState.Update;
