import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StudentRoutes } from "../../student-routes";
import { studentSession } from "../auth/auth-session";

/**
 * FE-018 — Knowledge graph route (`/map/graph`) integration tests.
 *
 * These cover the LearningGraphPage wiring: the route mounts, fixture mode
 * renders the chart figure, the legend counts come from the fixture nodes,
 * the map<->graph nav links exist in both directions, and clicking a node
 * opens the detail panel.
 *
 * The chart package's own unit tests (packages/charts/src/knowledge-graph.test.tsx)
 * cover the option builder and the click contract in detail; here we only
 * assert the page-level wiring so this file stays fast.
 */

let lastClickHandler: ((params: unknown) => void) | null = null;
const fakeInstance = { dispatchAction: vi.fn(), resize: vi.fn() };

vi.mock("echarts-for-react", () => {
  const React = require("react");
  const Mock = (props: {
    option: unknown;
    onEvents?: Record<string, (params: unknown) => void>;
    onChartReady?: (instance: unknown) => void;
  }) => {
    lastClickHandler = props.onEvents?.click ?? null;
    React.useEffect(() => {
      props.onChartReady?.(fakeInstance);
    }, []);
    return <div data-testid="echarts-graph">echarts mock</div>;
  };
  return { default: Mock };
});

function renderRoute(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <StudentRoutes initialSession={studentSession} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  lastClickHandler = null;
  fakeInstance.dispatchAction.mockClear();
});

describe("/map/graph route", () => {
  it("mounts the knowledge graph figure and surfaces node + edge counts", () => {
    renderRoute("/map/graph");

    const figure = screen.getByRole("figure", { name: "知识依赖图谱" });
    expect(figure).toBeVisible();
    // Fixture has 6 nodes / 5 edges; the accessible summary lists both.
    expect(figure).toHaveTextContent("节点数");
    expect(figure).toHaveTextContent("6");
    expect(figure).toHaveTextContent("前置依赖");
    expect(figure).toHaveTextContent("5");
  });

  it("renders every mastery bucket in the legend", () => {
    renderRoute("/map/graph");
    const legend = screen.getByRole("list", { name: "掌握状态图例" });
    expect(legend).toHaveTextContent("未开始");
    expect(legend).toHaveTextContent("学习中");
    expect(legend).toHaveTextContent("稳定掌握");
    expect(legend).toHaveTextContent("需要复测");
  });

  it("provides back-navigation to the flat learning map", () => {
    renderRoute("/map/graph");
    const back = screen.getByRole("link", { name: "返回学习地图" });
    expect(back).toHaveAttribute("href", "/map");
  });

  it("links from /map to the graph view", () => {
    renderRoute("/map");
    // The sidebar also exposes a 知识图谱 entry now (Stage C1), so scope the
    // assertion to the in-page heading action that lives inside the map page.
    const headingActions = document.querySelector(".map-heading-actions");
    const graphLink = within(headingActions as HTMLElement).getByRole("link", {
      name: "知识图谱",
    });
    expect(graphLink).toHaveAttribute("href", "/map/graph");
  });

  it("opens the node detail panel on a chart click", async () => {
    renderRoute("/map/graph");
    expect(lastClickHandler).not.toBeNull();

    lastClickHandler?.({ data: { id: "node-collections", name: "列表与字典" } });

    const panelHeading = await screen.findByRole("heading", {
      name: "列表与字典",
    });
    const panel = panelHeading.closest("aside");
    expect(panel).not.toBeNull();
    expect(panel).toHaveTextContent("未开始");
    expect(panel).toHaveTextContent("ch-04");
    expect(panel).toHaveTextContent("node-collections");
  });

  it("clears the panel and dispatches restore on reset", async () => {
    const user = userEvent.setup();
    renderRoute("/map/graph");

    lastClickHandler?.({ data: { id: "node-collections", name: "列表与字典" } });
    await screen.findByRole("heading", { name: "列表与字典" });

    await user.click(screen.getByRole("button", { name: "重置视图" }));
    expect(fakeInstance.dispatchAction).toHaveBeenCalledWith({
      type: "restore",
    });
    expect(
      screen.getByRole("heading", { name: "点击节点查看详情" }),
    ).toBeVisible();
  });

  it("keeps the mastery status server-owned (no browser mutation on click)", async () => {
    renderRoute("/map/graph");
    lastClickHandler?.({ data: { id: "node-functions", name: "函数基础" } });

    const panelHeading = await screen.findByRole("heading", {
      name: "函数基础",
    });
    const panel = panelHeading.closest("aside");
    const statusCell = panel?.querySelector("[data-status]");
    expect(statusCell).toHaveAttribute("data-status", "LEARNING");
  });

  it("shows the demo-guest empty state for demo sessions", () => {
    const demoSession = {
      ...studentSession,
      displayName: "演示访客",
      role: "demo" as const,
      userId: "demo-001",
    };
    render(
      <MemoryRouter initialEntries={["/map/graph"]}>
        <StudentRoutes initialSession={demoSession} />
      </MemoryRouter>,
    );
    // within() keeps the query scoped to the empty-state panel even if the
    // surrounding layout happens to render a similar phrase elsewhere.
    expect(
      within(document.body).getByRole("status", {
        name: "演示账号使用预置路径",
      }),
    ).toBeVisible();
  });
});
