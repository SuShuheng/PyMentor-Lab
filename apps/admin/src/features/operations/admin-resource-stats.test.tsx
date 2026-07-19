import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { saveServerUrl } from "@pymentor/config";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminRoutes } from "../../admin-routes";
import { adminSession } from "../auth/auth-session";

const liveAdminSession = {
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

function renderAdmin(route: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[route]}>
        <AdminRoutes initialSession={liveAdminSession} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const RESOURCE_TYPES = [
  "MICRO_LECTURE",
  "STRUCTURE_CARD",
  "LAYERED_EXERCISE",
  "NOTEBOOK_TASK",
  "TRACE_ANIMATION",
] as const;

/**
 * Build a minimal BE-028 `GET /api/v1/admin/metrics` payload. FE-026 only
 * consumes the `resource_stats.items` field, so the FE-025 chart inputs are
 * stubbed as empty arrays.
 */
function metricsResponse(options: { courseId?: string | null } = {}) {
  const { courseId = null } = options;
  return {
    window: { bucket: "day", bucket_count: 7, since: "2026-07-12T00:00:00Z", until: "2026-07-19T00:00:00Z" },
    api_usage: { buckets: [] },
    mastery_distribution: { counts: {} },
    agent_timeline: { points: [] },
    resource_stats: {
      course_id: courseId,
      since: "2026-07-12T00:00:00Z",
      until: "2026-07-19T00:00:00Z",
      items: RESOURCE_TYPES.map((resource_type, index) => ({
        resource_type,
        total: 10 + index * 3,
        succeeded: 8 + index * 2,
        success_rate: 0.8 + index * 0.02,
        avg_generation_ms: 1200 + index * 350,
      })),
    },
  };
}

function reviewsResponse() {
  return {
    items: [],
    page: { number: 1, size: 20, total_items: 0, total_pages: 0 },
  };
}

describe("admin resource statistics (FE-026)", () => {
  it("renders BE-028 resource_stats counts, success rate and avg generation time per type", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.url.includes("/api/v1/admin/metrics")) {
        return new Response(JSON.stringify(metricsResponse()), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      if (request.url.includes("/api/v1/admin/resources/reviews")) {
        return new Response(JSON.stringify(reviewsResponse()), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      throw new Error(`Unexpected request: ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAdmin("/admin/resources/stats");

    const panel = await screen.findByRole("region", { name: "资源统计" });
    // Per-type count column from resource_stats. Each value renders twice
    // (visual gauge + accessible ChartFrame table), so we scope to the table.
    const table = within(panel).getByRole("table", { name: "资源生成统计数据" });
    expect(await within(table).findByText("MICRO_LECTURE")).toBeVisible();
    expect(within(table).getByText("STRUCTURE_CARD")).toBeVisible();
    expect(within(table).getByText("LAYERED_EXERCISE")).toBeVisible();
    expect(within(table).getByText("NOTEBOOK_TASK")).toBeVisible();
    expect(within(table).getByText("TRACE_ANIMATION")).toBeVisible();
    // Counts rendered from BE-028 totals (10, 13, 16, 19, 22).
    expect(within(table).getByText("10")).toBeVisible();
    expect(within(table).getByText("22")).toBeVisible();
    // Success rate (0.8 -> 80.0%) and avg generation time rendered for the
    // first row.
    expect(within(table).getByText("80.0%")).toBeVisible();
    expect(within(table).getByText("1.2s")).toBeVisible();

    const metricsRequest = fetchMock.mock.calls.find(([request]) =>
      (request as Request).url.includes("/api/v1/admin/metrics"),
    )?.[0] as Request;
    expect(metricsRequest.headers.get("Authorization")).toBe("Bearer admin-access");
  });

  it("forwards date-range and course_id filters to BE-028 via the shared FE-025 wrapper", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.url.includes("/api/v1/admin/metrics")) {
        return new Response(JSON.stringify(metricsResponse()), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      if (request.url.includes("/api/v1/admin/resources/reviews")) {
        return new Response(JSON.stringify(reviewsResponse()), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      throw new Error(`Unexpected request: ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/resources/stats");

    await screen.findByRole("region", { name: "资源统计" });

    // jsdom does not synthesize native date-input values from userEvent.type,
    // so drive the filters through native change events.
    fireEvent.change(screen.getByLabelText("起始日期"), { target: { value: "2026-07-01" } });
    fireEvent.change(screen.getByLabelText("结束日期"), { target: { value: "2026-07-18" } });
    fireEvent.change(screen.getByLabelText("课程 ID"), { target: { value: "course-728" } });
    await user.click(screen.getByRole("button", { name: "应用筛选" }));

    await waitFor(() => {
      const metricsUrls = fetchMock.mock.calls.map(
        ([request]) => (request as Request).url,
      );
      // The filtered fetch is the second /metrics call; assert against the
      // most recent one so the unfiltered initial call does not mask it.
      const filteredUrl = [...metricsUrls]
        .reverse()
        .find((url) => url.includes("/api/v1/admin/metrics"));
      expect(filteredUrl).toContain("since=2026-07-01");
      expect(filteredUrl).toContain("until=2026-07-18");
      expect(filteredUrl).toContain("course_id=course-728");
    });
  });

  it("exports the current resource_stats rows as a CSV download via the shared FE-025 helper", async () => {
    saveServerUrl("https://api.example.test");
    const createObjectURL = vi.fn(() => "blob:resource-stats");
    const revokeObjectURL = vi.fn();
    const clickSpy = vi.fn();
    // Preserve the real URL constructor + URLSearchParams so the FE-025
    // fetcher's query builder keeps working; only stub the object-URL hooks.
    vi.stubGlobal("URL", Object.assign(class extends globalThis.URL {}, {
      createObjectURL,
      revokeObjectURL,
    }));
    // Capture the Blob parts so we can assert the CSV payload without relying
    // on jsdom's Blob.text() (not implemented in this jsdom build). Wrap the
    // real class so createObjectURL still receives a valid Blob instance.
    const RealBlob = globalThis.Blob;
    const blobCalls: { parts: BlobPart[]; options: BlobPropertyBag }[] = [];
    const CapturingBlob = vi.fn().mockImplementation((parts: BlobPart[], options: BlobPropertyBag) => {
      blobCalls.push({ parts, options });
      return new RealBlob(parts, options);
    }) as unknown as typeof Blob;
    vi.stubGlobal("Blob", CapturingBlob);
    const originalCreateElement = document.createElement.bind(document);
    const anchorClickDescriptor = Object.getOwnPropertyDescriptor(
      HTMLAnchorElement.prototype,
      "click",
    );
    vi.spyOn(document, "createElement").mockImplementation((tagName: string) => {
      const node = originalCreateElement(tagName);
      if (tagName === "a") {
        Object.defineProperty(node, "click", { value: clickSpy });
      }
      return node;
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.url.includes("/api/v1/admin/metrics")) {
        return new Response(JSON.stringify(metricsResponse()), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      if (request.url.includes("/api/v1/admin/resources/reviews")) {
        return new Response(JSON.stringify(reviewsResponse()), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      throw new Error(`Unexpected request: ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/resources/stats");

    await screen.findByRole("region", { name: "资源统计" });
    await user.click(screen.getByRole("button", { name: "导出 CSV" }));

    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    expect(blobCalls).toHaveLength(1);
    const captured = blobCalls[0];
    if (!captured) throw new Error("Blob constructor was not called");
    const { parts: blobParts, options: blobOptions } = captured;
    expect(blobOptions.type).toBe("text/csv;charset=utf-8");
    const csv = blobParts.map((part: BlobPart) => String(part)).join("");
    expect(csv).toContain("resource_type,total,succeeded,success_rate,avg_generation_ms");
    expect(csv).toContain("MICRO_LECTURE,10,8,0.800,1200");
    expect(csv).toContain("TRACE_ANIMATION,22,16,0.880,2600");
    expect(clickSpy).toHaveBeenCalledTimes(1);

    // Restore the spied anchor prototype so the next test's unmount is clean.
    if (anchorClickDescriptor) {
      Object.defineProperty(HTMLAnchorElement.prototype, "click", anchorClickDescriptor);
    }
    vi.restoreAllMocks();
  });

  it("falls back to an error state with retry when BE-028 fails", async () => {
    saveServerUrl("https://api.example.test");
    let failing = true;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.url.includes("/api/v1/admin/metrics")) {
        if (failing) {
          return new Response(JSON.stringify({ detail: "租户资源统计不可用" }), {
            headers: { "Content-Type": "application/json" },
            status: 503,
          });
        }
        return new Response(JSON.stringify(metricsResponse()), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      if (request.url.includes("/api/v1/admin/resources/reviews")) {
        return new Response(JSON.stringify(reviewsResponse()), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      throw new Error(`Unexpected request: ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/resources/stats");

    const alert = await screen.findByRole("alert", { name: "资源统计错误" });
    expect(alert).toHaveTextContent("租户资源统计不可用");

    failing = false;
    await user.click(screen.getByRole("button", { name: "重试统计" }));
    const panel = await screen.findByRole("region", { name: "资源统计" });
    const table = within(panel).getByRole("table", { name: "资源生成统计数据" });
    expect(await within(table).findByText("MICRO_LECTURE")).toBeVisible();
  });
});
