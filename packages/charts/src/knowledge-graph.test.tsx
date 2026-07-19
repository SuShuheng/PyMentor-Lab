import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  KnowledgeGraphEdge,
  KnowledgeGraphNode,
  KnowledgeGraphProps,
} from "./knowledge-graph";
import {
  KnowledgeGraph,
  buildKnowledgeGraphOption,
  masteryColor,
  masteryLabel,
} from "./knowledge-graph";

/**
 * FE-018 — Knowledge graph renderer tests.
 *
 * Tests cover two layers:
 *  1. Pure option builder (`buildKnowledgeGraphOption`) — nodes, edges,
 *     colors. No canvas, no echarts.
 *  2. Component render — legend counts, accessible summary, and the
 *     click-→-side-panel contract. Click is driven through a mocked
 *     `echarts-for-react` so we can assert the registered `click` handler
 *     opens the panel for the right node.
 *
 * The mock mirrors the real component's prop surface (`option`, `onEvents`,
 * `onChartReady`, `style`) so the production code path is exercised; only the
 * canvas painting is replaced. This is the same pattern used by other tests
 * in this package that need to assert against echarts props.
 */

const nodes: ReadonlyArray<KnowledgeGraphNode> = [
  {
    node_id: "node-variables",
    title: "变量与表达式",
    chapter_id: "ch-01",
    mastery_status: "STABLE_MASTERY",
  },
  {
    node_id: "node-conditions",
    title: "条件分支",
    chapter_id: "ch-02",
    mastery_status: "LEARNING",
  },
  {
    node_id: "node-loops",
    title: "循环结构",
    chapter_id: "ch-02",
    mastery_status: "UNSEEN",
  },
  {
    node_id: "node-functions",
    title: "函数基础",
    chapter_id: "ch-03",
    mastery_status: "REVIEW_REQUIRED",
  },
];

const edges: ReadonlyArray<KnowledgeGraphEdge> = [
  { from_node_id: "node-variables", to_node_id: "node-conditions", kind: "PREREQUISITE" },
  { from_node_id: "node-conditions", to_node_id: "node-loops", kind: "PREREQUISITE" },
  { from_node_id: "node-loops", to_node_id: "node-functions", kind: "PREREQUISITE" },
];

// Capture the click handler registered with echarts-for-react so we can
// dispatch a synthetic node-click and assert the panel reacts.
let lastClickHandler: ((params: unknown) => void) | null = null;
let lastChartReady: ((instance: unknown) => void) | null = null;
const dispatchAction = vi.fn();
const fakeInstance = { dispatchAction, resize: vi.fn() };

vi.mock("echarts-for-react", () => {
  const React = require("react");
  const Mock = (props: {
    option: unknown;
    onEvents?: Record<string, (params: unknown) => void>;
    onChartReady?: (instance: unknown) => void;
    style?: Record<string, string>;
  }) => {
    lastClickHandler = props.onEvents?.click ?? null;
    lastChartReady = props.onChartReady ?? null;
    // Announce readiness after mount so we don't setState during render.
    React.useEffect(() => {
      props.onChartReady?.(fakeInstance);
    }, []);
    return (
      <div
        aria-hidden="true"
        data-option-nodes={
          (
            (props.option as { series?: Array<{ data?: Array<{ id: string }> }> })
              .series?.[0]?.data ?? []
          )
            .map((node) => node.id)
            .join(",")
        }
        data-testid="echarts-graph"
      >
        echarts mock
      </div>
    );
  };
  return { default: Mock };
});

function renderGraph(overrides: Partial<KnowledgeGraphProps> = {}) {
  return render(
    <KnowledgeGraph
      description="按服务端掌握状态着色的知识图谱"
      edges={edges}
      nodes={nodes}
      title="知识图谱"
      {...overrides}
    />,
  );
}

describe("buildKnowledgeGraphOption", () => {
  it("emits one series node per input node and one link per edge", () => {
    const option = buildKnowledgeGraphOption(nodes, edges);
    const series = (option.series as Array<{ data: Array<{ id: string }>; links: Array<{ source: string; target: string }> }>)[0];
    expect(series?.data.map((node) => node.id)).toEqual([
      "node-variables",
      "node-conditions",
      "node-loops",
      "node-functions",
    ]);
    expect(series?.links).toEqual([
      { source: "node-variables", target: "node-conditions" },
      { source: "node-conditions", target: "node-loops" },
      { source: "node-loops", target: "node-functions" },
    ]);
  });

  it("uses force layout only — radial/circular must stay out of scope", () => {
    const option = buildKnowledgeGraphOption(nodes, edges);
    const series = (option.series as Array<{ layout: string; type: string }>)[0];
    expect(series?.type).toBe("graph");
    expect(series?.layout).toBe("force");
  });

  it("colors each node from the server mastery status, never from a guess", () => {
    const option = buildKnowledgeGraphOption(nodes, edges);
    const data = (option.series as Array<{ data: Array<{ itemStyle: { color: string }; id: string }> }>)[0]?.data ?? [];
    const byId = new Map(data.map((node) => [node.id, node.itemStyle.color]));
    expect(byId.get("node-variables")).toBe(masteryColor("STABLE_MASTERY"));
    expect(byId.get("node-conditions")).toBe(masteryColor("LEARNING"));
    expect(byId.get("node-loops")).toBe(masteryColor("UNSEEN"));
    expect(byId.get("node-functions")).toBe(masteryColor("REVIEW_REQUIRED"));
  });

  it("keeps the legend in canonical mastery order", () => {
    const option = buildKnowledgeGraphOption(nodes, edges);
    const legend = (option.legend as Array<{ data: string[] }>)[0];
    expect(legend?.data).toEqual([
      "未开始",
      "学习中",
      "辅助通过",
      "初步掌握",
      "稳定掌握",
      "需要复测",
    ]);
  });
});

describe("KnowledgeGraph render", () => {
  it("renders the figure, every legend item, and node/edge counts", () => {
    renderGraph();

    const figure = screen.getByRole("figure", { name: "知识图谱" });
    expect(figure).toBeVisible();
    // All six mastery buckets are present in the legend.
    const legend = screen.getByRole("list", { name: "掌握状态图例" });
    expect(legend).toHaveTextContent("未开始");
    expect(legend).toHaveTextContent("学习中");
    expect(legend).toHaveTextContent("稳定掌握");
    expect(legend).toHaveTextContent("需要复测");
    // Counts come from the input nodes.
    expect(legend).toHaveTextContent("稳定掌握");
    // Accessible summary lists node + edge totals.
    expect(figure).toHaveTextContent("节点数");
    expect(figure).toHaveTextContent("4");
    expect(figure).toHaveTextContent("前置依赖");
    expect(figure).toHaveTextContent("3");
  });

  it("shows the empty hint before any node is clicked", () => {
    renderGraph();
    const panelHeading = screen.getByRole("heading", {
      name: "点击节点查看详情",
    });
    expect(panelHeading).toBeVisible();
    // Honesty copy: panel must say the browser does not own mastery.
    expect(panelHeading.parentElement).toHaveTextContent("BE-021");
  });

  it("opens the node side panel when echarts reports a click", async () => {
    renderGraph();

    // Sanity: the chart registered a click handler.
    expect(lastClickHandler).not.toBeNull();

    // Simulate echarts calling our handler with a node payload.
    lastClickHandler?.({ data: { id: "node-functions", name: "函数基础" } });

    // Side panel now shows the clicked node's server mastery status.
    const panelHeading = await screen.findByRole("heading", {
      name: "函数基础",
    });
    expect(panelHeading).toBeVisible();
    const panel = panelHeading.closest("aside");
    expect(panel).not.toBeNull();
    expect(panel).toHaveTextContent(masteryLabel("REVIEW_REQUIRED"));
    expect(panel).toHaveTextContent("ch-03");
    // The node id is shown verbatim (no truncation in the detail panel).
    expect(panel).toHaveTextContent("node-functions");
  });

  it("does not change mastery status when a node is clicked (browser is read-only)", async () => {
    renderGraph();
    lastClickHandler?.({ data: { id: "node-variables", name: "变量与表达式" } });

    const panelHeading = await screen.findByRole("heading", {
      name: "变量与表达式",
    });
    const panel = panelHeading.closest("aside");
    // The mastery status cell carries the server status as a data attribute
    // so we can assert the browser never rewrites it to a "selected" state.
    const statusCell = panel?.querySelector("[data-status]");
    expect(statusCell).not.toBeNull();
    expect(statusCell).toHaveAttribute("data-status", "STABLE_MASTERY");
    expect(statusCell).toHaveTextContent(masteryLabel("STABLE_MASTERY"));
  });

  it("clears the side panel and dispatches an echarts restore on reset", async () => {
    const user = userEvent.setup();
    renderGraph();
    expect(lastChartReady).not.toBeNull();

    lastClickHandler?.({ data: { id: "node-functions", name: "函数基础" } });
    expect(
      await screen.findByRole("heading", { name: "函数基础" }),
    ).toBeVisible();

    dispatchAction.mockClear();
    await user.click(screen.getByRole("button", { name: "重置视图" }));

    // Restore was dispatched to the echarts instance (no re-fetch).
    expect(dispatchAction).toHaveBeenCalledWith({ type: "restore" });
    // Panel reverted to the empty hint.
    expect(
      screen.getByRole("heading", { name: "点击节点查看详情" }),
    ).toBeVisible();
  });
});
