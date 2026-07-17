import {
  AgentProposalEnvelope,
  type AgentNodeName,
  type SpecialistAgentNodeName,
  type WorkerJobEnvelope,
  type WorkerJobKind,
} from "@pymentor/contracts";
import { MemorySaver } from "@langchain/langgraph";
import { describe, expect, it } from "vitest";

import { buildAgentGraph, WorkflowPolicyError } from "./graph.js";

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
      now: () => new Date("2026-07-17T12:01:00.000Z"),
    });

    const result = await runtime.invoke(jobFor("coding_coach"), {
      threadId: "run-fallback",
    });

    expect(result.envelope.fallback_used).toBe(true);
    expect(result.envelope.proposal).toMatchObject({ kind: "coaching_feedback" });
  });
});
