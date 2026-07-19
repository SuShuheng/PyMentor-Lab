/**
 * Stage C1+C2 — Sidebar nav items for 知识图谱 / 个性化资源, and KG node →
 * resources/practice links.
 *
 * Covers three user-reported problems:
 *  - "知识图谱应该单开一个左侧边栏选项" (problem 6)
 *  - "个性化资源应该单开一个左侧边栏选项" (problem 7)
 *  - "知识图谱支持选中知识点后跳转到对应的知识库、题库等个性化资源页面"
 *    (problem 6)
 *
 * The chart canvas is mocked (same pattern as knowledge-graph.test.tsx) so we
 * can drive the registered click handler and assert the side panel exposes
 * action links without painting echarts.
 */
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StudentRoutes } from "../../student-routes";
import { studentSession } from "../auth/auth-session";

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

describe("Stage C1 — sidebar exposes 知识图谱 and 个性化资源 entries", () => {
  it("lists 知识图谱 in the primary navigation pointing at /map/graph", () => {
    renderRoute("/today");
    const nav = screen.getByRole("navigation", { name: "主导航" });
    const graphLink = within(nav).getByRole("link", { name: "知识图谱" });
    expect(graphLink).toHaveAttribute("href", "/map/graph");
  });

  it("lists 个性化资源 in the primary navigation pointing at /resources", () => {
    renderRoute("/today");
    const nav = screen.getByRole("navigation", { name: "主导航" });
    const resourcesLink = within(nav).getByRole("link", { name: "个性化资源" });
    expect(resourcesLink).toHaveAttribute("href", "/resources");
  });

  it("navigates to the knowledge graph page from the sidebar entry", () => {
    // Landing on /map/graph shows the figure; the sidebar entry for 知识图谱
    // is the current page (aria-current=page) on that route.
    renderRoute("/map/graph");
    expect(screen.getByRole("figure", { name: "知识依赖图谱" })).toBeVisible();
    const nav = screen.getByRole("navigation", { name: "主导航" });
    const graphLink = within(nav).getByRole("link", { name: "知识图谱" });
    expect(graphLink).toHaveAttribute("aria-current", "page");
  });
});

describe("Stage C2 — KG node side panel links to resources and practice", () => {
  it("shows a 查看该节点资源 link carrying the selected node id", async () => {
    renderRoute("/map/graph");
    expect(lastClickHandler).not.toBeNull();
    lastClickHandler?.({ data: { id: "node-functions", name: "函数基础" } });

    const panelHeading = await screen.findByRole("heading", { name: "函数基础" });
    const panel = panelHeading.closest("aside");
    expect(panel).not.toBeNull();
    const resourceLink = within(panel!).getByRole("link", {
      name: /查看该节点资源/,
    });
    // The node id is forwarded as a query param so ResourcesPage can filter.
    expect(resourceLink).toHaveAttribute(
      "href",
      expect.stringContaining("/resources"),
    );
    expect(resourceLink.getAttribute("href")).toContain(
      encodeURIComponent("node-functions"),
    );
  });

  it("shows a 该节点自测 link pointing at the practice route for the node", async () => {
    renderRoute("/map/graph");
    lastClickHandler?.({ data: { id: "node-loops", name: "循环结构" } });

    const panelHeading = await screen.findByRole("heading", { name: "循环结构" });
    const panel = panelHeading.closest("aside");
    const practiceLink = within(panel!).getByRole("link", { name: /该节点自测/ });
    expect(practiceLink).toHaveAttribute("href", "/practice/node-loops");
  });

  it("omits the action links before any node is selected", () => {
    renderRoute("/map/graph");
    // No node selected yet — the action links must not render.
    expect(screen.queryByRole("link", { name: /查看该节点资源/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /该节点自测/ })).toBeNull();
  });
});

describe("Stage C2 — ResourcesPage honors the ?node= filter param", () => {
  it("surfaces the active node filter in the heading region", () => {
    renderRoute("/resources?node=node-functions");
    // The page announces which node the resource pack is scoped to.
    const region = screen.getByLabelText(/当前节点/);
    expect(region).toHaveTextContent("node-functions");
  });
});
