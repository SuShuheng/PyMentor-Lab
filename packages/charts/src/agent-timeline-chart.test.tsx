import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AgentTimelinePoint } from "./admin-metrics-types";
import { AgentTimelineChart, buildAgentTimelineOption } from "./agent-timeline-chart";

const points: AgentTimelinePoint[] = [
  {
    run_id: "RUN-001",
    student_id: "stu-1",
    route: "orchestrator",
    status: "SUCCEEDED",
    fallback: false,
    started_at: "2026-07-19T02:00:00Z",
    ended_at: "2026-07-19T02:00:30Z",
    latency_ms: 30000,
  },
  {
    run_id: "RUN-002",
    student_id: "stu-2",
    route: "tutor.fallback",
    status: "SUCCEEDED",
    fallback: true,
    started_at: "2026-07-19T02:01:00Z",
    ended_at: "2026-07-19T02:01:45Z",
    latency_ms: 45000,
  },
  {
    run_id: "RUN-003",
    student_id: null,
    route: "grader",
    status: "FAILED",
    fallback: false,
    started_at: "2026-07-19T02:02:00Z",
    ended_at: null,
    latency_ms: null,
  },
];

describe("AgentTimelineChart option", () => {
  it("encodes one custom series point per run with start/end timestamps", () => {
    const option = buildAgentTimelineOption(points);
    const series = option.series as Array<{
      type: string;
      data: Array<{ value: (string | number | boolean)[] }>;
    }>;
    expect(series).toHaveLength(1);
    expect(series[0]?.type).toBe("custom");
    const data = series[0]?.data ?? [];
    expect(data).toHaveLength(3);
    // reversed in the option so RUN-001 sits at the bottom
    const topRun = data[0]?.value;
    expect(topRun?.[3]).toBe("FAILED"); // RUN-003 status
    expect(topRun?.[2]).toBeGreaterThan(topRun?.[1] as number); // end > start
  });

  it("extends in-flight runs (ended_at=null) to a synthetic end > start", () => {
    const option = buildAgentTimelineOption([points[2]!]);
    const series = option.series as Array<{
      data: Array<{ value: number[] }>;
    }>;
    const value = series[0]?.data[0]?.value;
    expect(value?.[2]).toBeGreaterThan(value?.[1] as number);
  });

  it("handles an empty points list without throwing", () => {
    expect(() => buildAgentTimelineOption([])).not.toThrow();
    const option = buildAgentTimelineOption([]);
    expect(Array.isArray(option.series)).toBe(true);
  });
});

describe("AgentTimelineChart render", () => {
  it("exposes route, status, fallback and latency in the companion table", () => {
    render(<AgentTimelineChart points={points} />);
    const table = screen.getByRole("table", { name: "Agent 执行时间线数据" });
    expect(table).toHaveTextContent("RUN-001");
    expect(table).toHaveTextContent("orchestrator");
    expect(table).toHaveTextContent("SUCCEEDED");
    expect(table).toHaveTextContent("RUN-002");
    expect(table).toHaveTextContent("是"); // fallback = 是
    expect(table).toHaveTextContent("30000ms");
    expect(table).toHaveTextContent("—"); // null latency for RUN-003
  });
});
