import { render, screen, waitFor, within } from "@testing-library/react";
import { saveServerUrl } from "@pymentor/config";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminRoutes } from "../../admin-routes";
import { adminSession, type AuthSession } from "../auth/auth-session";

const liveAdminSession: AuthSession = {
  ...adminSession,
  accessToken: "admin-access",
};

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { gcTime: 0, retry: false, staleTime: 0 },
    },
  });
}

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

function renderAdmin(route: string, session: AuthSession = liveAdminSession) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[route]}>
        <AdminRoutes initialSession={session} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Minimal BE-028 `GET /api/v1/admin/metrics` payload with non-empty chart
 * inputs, including a bucket whose p50/p95 are null (gap handling). */
function advancedMetricsResponse() {
  return {
    window: {
      bucket: "hour",
      bucket_count: 3,
      since: "2026-07-19T00:00:00Z",
      until: "2026-07-19T03:00:00Z",
    },
    api_usage: {
      buckets: [
        {
          bucket_start: "2026-07-19T00:00:00Z",
          total: 120,
          p50: 90,
          p95: 240,
          error_rate: 0.05,
          throttle_rate: 0.01,
        },
        {
          bucket_start: "2026-07-19T01:00:00Z",
          total: 0,
          p50: null,
          p95: null,
          error_rate: 0,
          throttle_rate: 0,
        },
        {
          bucket_start: "2026-07-19T02:00:00Z",
          total: 80,
          p50: 110,
          p95: 300,
          error_rate: 0.1,
          throttle_rate: 0.02,
        },
      ],
    },
    mastery_distribution: {
      counts: {
        UNSEEN: 12,
        LEARNING: 34,
        PASSED_WITH_HELP: 8,
        INITIAL_MASTERY: 21,
        STABLE_MASTERY: 40,
        REVIEW_REQUIRED: 5,
      },
    },
    agent_timeline: {
      points: [
        {
          run_id: "RUN-ADV-001",
          student_id: "stu-adv-1",
          route: "orchestrator",
          status: "SUCCEEDED",
          fallback: false,
          started_at: "2026-07-19T02:00:00Z",
          ended_at: "2026-07-19T02:00:30Z",
          latency_ms: 30000,
        },
        {
          run_id: "RUN-ADV-002",
          student_id: "stu-adv-2",
          route: "tutor.fallback",
          status: "SUCCEEDED",
          fallback: true,
          started_at: "2026-07-19T02:01:00Z",
          ended_at: "2026-07-19T02:01:45Z",
          latency_ms: 45000,
        },
      ],
    },
    resource_stats: { course_id: null, items: [] },
  };
}

/** Stub `fetch` so BE-028 returns `payload` and every other admin call returns
 * an empty 200. Returns the mock so the test can assert on request URLs. */
function stubFetchWithMetrics(payload: unknown) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.url.includes("/api/v1/admin/metrics")) {
      return new Response(JSON.stringify(payload), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      });
    }
    if (request.url.includes("/api/v1/admin/system/metrics")) {
      return new Response(JSON.stringify({ items: [], since: "", until: "" }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      });
    }
    return new Response(JSON.stringify({ items: [] }), {
      headers: { "Content-Type": "application/json" },
      status: 200,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("admin advanced metrics (FE-025)", () => {
  it("renders the three BE-028 charts with their series and gap markers", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = stubFetchWithMetrics(advancedMetricsResponse());

    renderAdmin("/admin/metrics");

    // API usage chart: bucket table includes the null-latency gap marker.
    const apiUsage = await screen.findByRole("figure", { name: "API 用量与延迟" });
    expect(within(apiUsage).getByRole("columnheader", { name: "请求量" })).toBeVisible();
    expect(within(apiUsage).getByRole("columnheader", { name: "P95" })).toBeVisible();
    // Empty bucket row carries the gap marker, never 0ms.
    const emptyRow = within(apiUsage)
      .getAllByRole("row")
      .find((row) => row.textContent?.includes("2026-07-19T01:00:00Z"));
    expect(emptyRow?.textContent ?? "").toContain("—");

    // Mastery distribution: every status label is listed (legend + table row).
    const mastery = screen.getByRole("figure", { name: "掌握状态分布" });
    const masteryTable = within(mastery).getByRole("table", { name: "掌握状态分布数据" });
    expect(within(masteryTable).getByRole("rowheader", { name: "稳定掌握" })).toBeVisible();
    expect(within(masteryTable).getByText("40")).toBeVisible();
    expect(within(masteryTable).getByRole("rowheader", { name: "待复测" })).toBeVisible();

    // Agent timeline: route / status / fallback exposed.
    const timeline = screen.getByRole("figure", { name: "Agent 执行时间线" });
    const timelineTable = within(timeline).getByRole("table", {
      name: "Agent 执行时间线数据",
    });
    expect(within(timelineTable).getByText("RUN-ADV-001")).toBeVisible();
    expect(within(timelineTable).getByText("orchestrator")).toBeVisible();
    expect(within(timelineTable).getByText("RUN-ADV-002")).toBeVisible();
    expect(within(timelineTable).getByText("是")).toBeVisible();

    const metricsRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find((request) => request.url.includes("/api/v1/admin/metrics"));
    expect(metricsRequest?.headers.get("Authorization")).toBe("Bearer admin-access");
  });

  it("applies since/until/node/course filters to the BE-028 request", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = stubFetchWithMetrics(advancedMetricsResponse());
    const user = userEvent.setup();

    renderAdmin("/admin/metrics");

    // Wait for the filters form to render.
    const sinceInput = await screen.findByLabelText("起始日期");
    await user.type(sinceInput, "2026-07-19");
    await user.type(screen.getByLabelText("结束日期"), "2026-07-20");
    await user.type(screen.getByLabelText("节点 ID"), "node-filtered");
    await user.type(screen.getByLabelText("课程 ID"), "course-filtered");
    await user.click(screen.getByRole("button", { name: "应用筛选" }));

    await waitFor(() => {
      const metricsRequest = fetchMock.mock.calls
        .map(([request]) => request as Request)
        .filter((request) => request.url.includes("/api/v1/admin/metrics"))
        .at(-1);
      expect(metricsRequest?.url).toContain("since=2026-07-19");
      expect(metricsRequest?.url).toContain("until=2026-07-20");
      expect(metricsRequest?.url).toContain("node_id=node-filtered");
      expect(metricsRequest?.url).toContain("course_id=course-filtered");
    });
  });

  it("exports the three chart series as a single CSV download", async () => {
    saveServerUrl("https://api.example.test");
    stubFetchWithMetrics(advancedMetricsResponse());

    const clicks: string[] = [];
    const downloads: string[] = [];
    const originalCreate = document.createElement.bind(document);
    const createElementSpy = vi
      .spyOn(document, "createElement")
      .mockImplementation((tagName: string) => {
        const node = originalCreate(tagName) as HTMLAnchorElement;
        if (tagName === "a") {
          Object.defineProperty(node, "download", {
            get() {
              return downloads[downloads.length - 1];
            },
            set(value: string) {
              downloads.push(value);
            },
            configurable: true,
          });
          node.click = () => {
            clicks.push(node.download ?? "");
          };
        }
        return node;
      });

    const user = userEvent.setup();
    renderAdmin("/admin/metrics");

    await screen.findByRole("figure", { name: "API 用量与延迟" });
    await user.click(screen.getByRole("button", { name: "导出指标 CSV" }));

    expect(clicks).toHaveLength(1);
    expect(downloads[0]).toMatch(/^pymentor-metrics-.*\.csv$/);

    createElementSpy.mockRestore();
  });

  it("denies non-admin sessions with the course-admin guard", async () => {
    saveServerUrl("https://api.example.test");
    stubFetchWithMetrics(advancedMetricsResponse());

    renderAdmin(
      "/admin/metrics",
      // Route guard would already redirect, but the page defends in depth.
      {
        ...adminSession,
        accessToken: "student-access",
        role: "student",
      } as AuthSession,
    );

    // RequireAdmin short-circuits to the access-denied panel before the page
    // mounts; assert that the advanced charts never render.
    expect(screen.queryByRole("figure", { name: "API 用量与延迟" })).not.toBeInTheDocument();
    await screen.findByText("无权访问管理端");
  });

  it("surfaces a retryable error state when BE-028 fails", async () => {
    saveServerUrl("https://api.example.test");
    let failing = true;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.url.includes("/api/v1/admin/metrics")) {
        if (failing) {
          return new Response(JSON.stringify({ detail: "指标聚合超时" }), {
            headers: { "Content-Type": "application/json" },
            status: 503,
          });
        }
        return new Response(JSON.stringify(advancedMetricsResponse()), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      return new Response(JSON.stringify({ items: [] }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderAdmin("/admin/metrics");

    const alert = await screen.findByRole("alert", { name: "高级指标错误" });
    expect(alert).toHaveTextContent("指标聚合超时");

    failing = false;
    await user.click(screen.getByRole("button", { name: "重试高级指标" }));
    await screen.findByRole("figure", { name: "API 用量与延迟" });
  });
});
