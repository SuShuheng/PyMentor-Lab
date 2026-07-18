import {
  AgentProposalEnvelope,
  type AgentNodeName,
  type SpecialistAgentNodeName,
  type WorkerJobEnvelope,
  type WorkerJobKind,
} from "@pymentor/contracts";
import { MemorySaver } from "@langchain/langgraph";
import { describe, expect, it } from "vitest";
import { z } from "zod";

import { buildAgentGraph, WorkflowPolicyError } from "./graph.js";
import { ToolRegistry } from "../agents/tool-registry.js";

const expectedRoute: Record<WorkerJobKind, SpecialistAgentNodeName> = {
  profile_diagnose: "profile",
  path_recommend: "path",
  resource_generate: "resource",
  tutoring_answer: "resource",
  coding_coach: "coach",
  assessment_feedback: "assessment",
};

const context = { evidence_event_ids: ["evidence-1"] };

const specialistInputs: Record<SpecialistAgentNodeName, unknown> = {
  profile: {
    evidence_summary: "The learner needs a boundary-condition review.",
    current_profile_version: 1,
    context,
  },
  path: {
    profile_summary: "The learner is ready for loop practice.",
    available_minutes: 30,
    candidate_node_ids: ["node-1"],
    context,
  },
  resource: {
    learning_need: "Explain loop boundary conditions.",
    resource_types: ["STRUCTURE_CARD"],
    tutoring_question: "Why is the upper bound exclusive?",
    context,
  },
  coach: {
    error_summary: "The loop skips its final element.",
    test_summary: "The boundary test fails for length one.",
    hint_level: 1,
    context,
  },
  assessment: {
    response_summary: "The learner explains the exclusive upper bound.",
    rubric_keys: ["CORRECTNESS"],
    context,
  },
};

const providerOutputs: Record<AgentNodeName, unknown> = {
  orchestrator: undefined,
  profile: {
    kind: "profile_change",
    changes: [
      {
        dimension: "BOUNDARY_REASONING",
        delta: 0.2,
        reason: "The evidence supports a small profile update.",
      },
    ],
  },
  path: {
    kind: "path_plan",
    steps: [
      {
        node_id: "node-1",
        action: "PRACTICE",
        reason: "Practice the validated candidate next.",
      },
    ],
  },
  resource: {
    kind: "resource_request",
    requests: [
      {
        resource_type: "STRUCTURE_CARD",
        objective: "Explain exclusive loop bounds.",
      },
    ],
    answer: "The upper bound is excluded by range semantics.",
  },
  coach: {
    kind: "coaching_feedback",
    diagnosis: "The loop condition stops one step too early.",
    hints: ["Compare the final index with the loop condition."],
    next_test: "Test lengths zero and one.",
  },
  assessment: {
    kind: "assessment_feedback",
    rubric_scores: { CORRECTNESS: 0.8 },
    feedback: "The explanation is mostly correct.",
    evidence_claims: ["The learner identified the exclusive upper bound."],
  },
};

function jobFor(kind: WorkerJobKind): WorkerJobEnvelope {
  const route = expectedRoute[kind];
  return {
    schema_version: 1,
    event_id: `event-${kind}`,
    trace_id: `trace-${kind}`,
    tenant_id: "tenant-1",
    student_id: "student-1",
    kind,
    payload: {
      request: `Handle ${kind} safely.`,
      agent_input: specialistInputs[route],
    },
    enqueued_at: "2026-07-17T12:00:00.000Z",
  };
}

function runtimeWithRouteOverride(override?: SpecialistAgentNodeName, checkpointer?: MemorySaver) {
  return buildAgentGraph({
    provider: {
      async complete(request) {
        if (request.node === "orchestrator") {
          const kind = (request.input as { kind: WorkerJobKind }).kind;
          return {
            route: override ?? expectedRoute[kind],
            intent_code: "ROUTE_REQUEST",
            summary: "Route the validated job to one specialist.",
          };
        }
        return providerOutputs[request.node];
      },
    },
    audit: { record: () => undefined },
    tools: new ToolRegistry({}),
    checkpointer,
    now: () => new Date("2026-07-17T12:01:00.000Z"),
  });
}

describe("agent workflow graph", () => {
  it("contains exactly six business nodes plus START and END", () => {
    const drawable = runtimeWithRouteOverride().compiled.getGraph();
    expect(Object.keys(drawable.nodes).sort()).toEqual([
      "__end__",
      "__start__",
      "assessment",
      "coach",
      "orchestrator",
      "path",
      "profile",
      "resource",
    ]);
  });

  it.each(Object.entries(expectedRoute) as [WorkerJobKind, SpecialistAgentNodeName][])(
    "routes %s through orchestrator to %s",
    async (kind, route) => {
      const result = await runtimeWithRouteOverride().invoke(jobFor(kind), {
        threadId: `run-${kind}`,
      });

      expect(result.executedNodes).toEqual(["orchestrator", route]);
      expect(result.auditSequence).toBe(4);
      expect(result.envelope.node).toBe(route);
      expect(AgentProposalEnvelope.parse(result.envelope)).toEqual(result.envelope);
    },
  );

  it("fails closed when the orchestrator chooses a route forbidden for the job kind", async () => {
    await expect(
      runtimeWithRouteOverride("assessment").invoke(jobFor("profile_diagnose"), {
        threadId: "run-route-mismatch",
      }),
    ).rejects.toBeInstanceOf(WorkflowPolicyError);
  });

  it("persists checkpoint-compatible state under the supplied thread identity", async () => {
    const checkpointer = new MemorySaver();
    const runtime = runtimeWithRouteOverride(undefined, checkpointer);

    await runtime.invoke(jobFor("path_recommend"), {
      threadId: "run-checkpoint",
    });
    const snapshot = await runtime.compiled.getState({
      configurable: { thread_id: "run-checkpoint" },
    });

    expect(snapshot.values.executedNodes).toEqual(["orchestrator", "path"]);
    expect(snapshot.values.proposal).toMatchObject({ kind: "path_plan" });
    expect(snapshot.next).toEqual([]);
  });

  it("resumes after the orchestrator checkpoint without rerunning the orchestrator", async () => {
    const checkpointer = new MemorySaver();
    const providerCalls: AgentNodeName[] = [];
    let failCoachAudit = true;
    const runtime = buildAgentGraph({
      provider: {
        async complete(request) {
          providerCalls.push(request.node);
          if (request.node === "orchestrator") {
            return {
              route: "coach",
              intent_code: "ROUTE_REQUEST",
              summary: "Route coding help to the coach.",
            };
          }
          return providerOutputs.coach;
        },
      },
      audit: {
        record(event) {
          if (event.node === "coach" && event.eventType === "NODE_STARTED" && failCoachAudit) {
            failCoachAudit = false;
            throw new Error("simulated transient audit outage");
          }
        },
      },
      tools: new ToolRegistry({}),
      checkpointer,
      now: () => new Date("2026-07-17T12:01:00.000Z"),
    });

    await expect(
      runtime.invoke(jobFor("coding_coach"), {
        threadId: "run-resume-after-orchestrator",
        agentRunId: "run-resume-after-orchestrator",
      }),
    ).rejects.toThrow(/transient audit outage/);

    const result = await runtime.resume({
      threadId: "run-resume-after-orchestrator",
      agentRunId: "run-resume-after-orchestrator",
    });

    expect(providerCalls).toEqual(["orchestrator", "coach"]);
    expect(result.executedNodes).toEqual(["orchestrator", "coach"]);
  });

  it("reserves distinct tool identities through the production graph context", async () => {
    const idempotencyKeys: string[] = [];
    const runtime = buildAgentGraph({
      provider: {
        async complete(request) {
          if (request.node === "orchestrator") {
            return {
              route: "coach",
              intent_code: "ROUTE_REQUEST",
              summary: "Route coding help to the coach.",
            };
          }
          await Promise.all([
            request.tools.invoke("sandbox.evidence.read", { evidence_id: "evidence-1" }),
            request.tools.invoke("sandbox.evidence.read", { evidence_id: "evidence-2" }),
          ]);
          return providerOutputs.coach;
        },
      },
      audit: { record: () => undefined },
      tools: new ToolRegistry({
        "sandbox.evidence.read": {
          inputSchema: z.object({ evidence_id: z.string() }).strict(),
          outputSchema: z.object({ ok: z.boolean() }).strict(),
          async invoke(_input, _signal, idempotencyKey) {
            idempotencyKeys.push(idempotencyKey);
            return { ok: true };
          },
        },
      }),
      now: () => new Date("2026-07-17T12:01:00.000Z"),
    });

    await runtime.invoke(jobFor("coding_coach"), {
      threadId: "run-parallel-tools",
      agentRunId: "run-parallel-tools",
    });

    expect(idempotencyKeys).toHaveLength(2);
    expect(new Set(idempotencyKeys).size).toBe(2);
  });

  it("propagates a specialist fallback into the proposal envelope", async () => {
    const runtime = buildAgentGraph({
      provider: {
        async complete(request) {
          if (request.node === "orchestrator") {
            return (
              providerOutputs.orchestrator ?? {
                route: "coach",
                intent_code: "ROUTE_REQUEST",
                summary: "Route coding help to the coach.",
              }
            );
          }
          return { invalid: true };
        },
      },
      audit: { record: () => undefined },
      tools: new ToolRegistry({}),
      now: () => new Date("2026-07-17T12:01:00.000Z"),
    });

    const result = await runtime.invoke(jobFor("coding_coach"), {
      threadId: "run-fallback",
    });

    expect(result.envelope.fallback_used).toBe(true);
    expect(result.envelope.proposal).toMatchObject({ kind: "coaching_feedback" });
  });
});
