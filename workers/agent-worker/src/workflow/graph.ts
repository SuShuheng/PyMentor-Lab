import { END, START, StateGraph, type BaseCheckpointSaver } from "@langchain/langgraph";
import {
  AgentContext,
  AgentProposalEnvelope,
  WorkerJobEnvelope,
  type AgentProposal,
  type SpecialistAgentNodeName,
} from "@pymentor/contracts";
import { z } from "zod";

import { executeNode } from "../agents/executor.js";
import { agentNodes } from "../agents/nodes.js";
import { EXPECTED_ROUTE_BY_KIND } from "../agents/policies.js";
import type {
  AgentAuditRecord,
  AgentAuditSink,
  AgentExecutionContext,
  AgentNodeDefinition,
  AgentProviderPort,
} from "../agents/types.js";
import { AgentWorkflowState, type AgentWorkflowStateValue } from "./state.js";

export { EXPECTED_ROUTE_BY_KIND };

const WorkflowPayload = z
  .object({
    request: z.string().min(1).max(4_000),
    agent_input: z.object({ context: AgentContext }).passthrough(),
  })
  .strict();

export class WorkflowPolicyError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "WorkflowPolicyError";
  }
}

export interface AgentGraphDependencies {
  readonly provider: AgentProviderPort;
  readonly audit: AgentAuditSink;
  readonly checkpointer?: BaseCheckpointSaver | false;
  readonly now?: () => Date;
}

export interface AgentGraphInvokeOptions {
  readonly threadId: string;
  readonly checkpointId?: string;
  readonly agentRunId?: string;
}

export interface AgentGraphResult {
  readonly envelope: AgentProposalEnvelope;
  readonly executedNodes: AgentWorkflowStateValue["executedNodes"];
  readonly auditSequence: number;
  readonly checkpointId?: string;
}

function createNodeContext(
  state: AgentWorkflowStateValue,
  dependencies: AgentGraphDependencies,
): {
  context: AgentExecutionContext;
  sequence: () => number;
  fallback: () => boolean;
} {
  let sequence = state.auditSequence;
  let fallback = false;
  return {
    context: {
      provider: dependencies.provider,
      eventId: state.job.event_id,
      audit: {
        record: async (event: AgentAuditRecord) => {
          sequence += 1;
          await dependencies.audit.record(event);
        },
      },
      onOutcome: (outcome) => {
        fallback = outcome.fallback;
      },
    },
    sequence: () => sequence,
    fallback: () => fallback,
  };
}

function workflowPayload(state: AgentWorkflowStateValue) {
  const parsed = WorkflowPayload.safeParse(state.job.payload);
  if (!parsed.success) {
    throw new WorkflowPolicyError(
      "INVALID_WORKFLOW_PAYLOAD",
      "Worker payload must contain a bounded request and one strict agent input.",
    );
  }
  return parsed.data;
}

function createSpecialistNode<TInput, TOutput extends AgentProposal>(
  name: SpecialistAgentNodeName,
  definition: AgentNodeDefinition<TInput, TOutput>,
  dependencies: AgentGraphDependencies,
) {
  return async (state: AgentWorkflowStateValue) => {
    const tracking = createNodeContext(state, dependencies);
    const proposal = await executeNode(
      definition,
      workflowPayload(state).agent_input,
      tracking.context,
    );
    return {
      proposal,
      executedNodes: [name],
      auditSequence: tracking.sequence(),
      fallbackUsed: tracking.fallback(),
    };
  };
}

function compileAgentGraph(dependencies: AgentGraphDependencies) {
  const orchestrator = async (state: AgentWorkflowStateValue) => {
    const payload = workflowPayload(state);
    const tracking = createNodeContext(state, dependencies);
    const output = await executeNode(
      agentNodes.orchestrator,
      {
        kind: state.job.kind,
        request: payload.request,
        context: payload.agent_input.context,
      },
      tracking.context,
    );
    const expectedRoute = EXPECTED_ROUTE_BY_KIND[state.job.kind];
    if (output.route !== expectedRoute) {
      throw new WorkflowPolicyError(
        "ROUTE_MISMATCH",
        `Job kind ${state.job.kind} may route only to ${expectedRoute}.`,
      );
    }
    return {
      route: output.route,
      executedNodes: ["orchestrator" as const],
      auditSequence: tracking.sequence(),
      fallbackUsed: tracking.fallback(),
    };
  };

  return new StateGraph(AgentWorkflowState)
    .addNode("orchestrator", orchestrator)
    .addNode("profile", createSpecialistNode("profile", agentNodes.profile, dependencies))
    .addNode("path", createSpecialistNode("path", agentNodes.path, dependencies))
    .addNode("resource", createSpecialistNode("resource", agentNodes.resource, dependencies))
    .addNode("coach", createSpecialistNode("coach", agentNodes.coach, dependencies))
    .addNode("assessment", createSpecialistNode("assessment", agentNodes.assessment, dependencies))
    .addEdge(START, "orchestrator")
    .addConditionalEdges("orchestrator", (state) => {
      if (state.route === null) {
        throw new WorkflowPolicyError("MISSING_ROUTE", "Orchestrator produced no route.");
      }
      return state.route;
    })
    .addEdge("profile", END)
    .addEdge("path", END)
    .addEdge("resource", END)
    .addEdge("coach", END)
    .addEdge("assessment", END)
    .compile({
      checkpointer: dependencies.checkpointer,
      name: "pymentor-agent-workflow-v1",
    });
}

export type CompiledAgentGraph = ReturnType<typeof compileAgentGraph>;

export interface AgentGraphRuntime {
  readonly compiled: CompiledAgentGraph;
  invoke(job: unknown, options: AgentGraphInvokeOptions): Promise<AgentGraphResult>;
  resume(options: AgentGraphInvokeOptions): Promise<AgentGraphResult>;
}

export function buildAgentGraph(dependencies: AgentGraphDependencies): AgentGraphRuntime {
  const compiled = compileAgentGraph(dependencies);
  return {
    compiled,
    invoke: (job, options) => invokeAgentGraph(compiled, dependencies, job, options),
    resume: (options) => resumeAgentGraph(compiled, dependencies, options),
  };
}

function graphConfig(options: AgentGraphInvokeOptions) {
  return {
    configurable: {
      thread_id: options.threadId,
      ...(options.checkpointId === undefined ? {} : { checkpoint_id: options.checkpointId }),
    },
  };
}

async function resultFromState(
  compiled: CompiledAgentGraph,
  dependencies: AgentGraphDependencies,
  state: AgentWorkflowStateValue,
  options: AgentGraphInvokeOptions,
): Promise<AgentGraphResult> {
  if (state.route === null || state.proposal === null) {
    throw new WorkflowPolicyError(
      "INCOMPLETE_WORKFLOW",
      "Agent graph ended without a specialist proposal.",
    );
  }

  const job = WorkerJobEnvelope.parse(state.job);
  const envelope = AgentProposalEnvelope.parse({
    schema_version: 1,
    agent_run_id: options.agentRunId ?? options.threadId,
    event_id: job.event_id,
    trace_id: job.trace_id,
    tenant_id: job.tenant_id,
    student_id: job.student_id,
    node: state.route,
    status: "SUCCEEDED",
    proposal: state.proposal,
    fallback_used: state.fallbackUsed,
    completed_at: (dependencies.now ?? (() => new Date()))().toISOString(),
  });
  const snapshot =
    dependencies.checkpointer === undefined || dependencies.checkpointer === false
      ? undefined
      : await compiled.getState(graphConfig(options));
  const checkpointId = snapshot?.config.configurable?.checkpoint_id;
  return {
    envelope,
    executedNodes: state.executedNodes,
    auditSequence: state.auditSequence,
    ...(typeof checkpointId === "string" ? { checkpointId } : {}),
  };
}

export async function invokeAgentGraph(
  compiled: CompiledAgentGraph,
  dependencies: AgentGraphDependencies,
  job: unknown,
  options: AgentGraphInvokeOptions,
): Promise<AgentGraphResult> {
  const parsedJob = WorkerJobEnvelope.parse(job);
  const state = await compiled.invoke({ job: parsedJob }, graphConfig(options));
  return resultFromState(compiled, dependencies, state, options);
}

export async function resumeAgentGraph(
  compiled: CompiledAgentGraph,
  dependencies: AgentGraphDependencies,
  options: AgentGraphInvokeOptions,
): Promise<AgentGraphResult> {
  const state = await compiled.invoke(null as never, graphConfig(options));
  return resultFromState(compiled, dependencies, state, options);
}
