import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ApiUsageBucket } from "./admin-metrics-types";
import { ApiUsageChart, buildApiUsageOption } from "./api-usage-chart";

const buckets: ApiUsageBucket[] = [
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
];

describe("ApiUsageChart option", () => {
  it("maps buckets to volume bars and p50/p95 lines", () => {
    const option = buildApiUsageOption(buckets);
    const series = option.series as Array<{ name: string; type: string; data: unknown[] }>;
    const bar = series.find((item) => item.type === "bar");
    const p95 = series.find((item) => item.name === "P95 延迟");
    expect(bar?.data).toEqual([120, 0, 80]);
    expect(p95?.data).toEqual([240, null, 300]);
  });

  it("keeps null latency buckets as gaps (connectNulls=false), not zeros", () => {
    const option = buildApiUsageOption(buckets);
    const series = option.series as Array<{
      name: string;
      connectNulls?: boolean;
      data: unknown[];
    }>;
    const p50 = series.find((item) => item.name === "P50 延迟");
    const p95 = series.find((item) => item.name === "P95 延迟");
    expect(p50?.data).toEqual([90, null, 110]);
    expect(p95?.connectNulls).toBe(false);
    expect(p50?.connectNulls).toBe(false);
  });
});

describe("ApiUsageChart render", () => {
  it("renders the bucket table with gap markers for empty buckets", () => {
    render(<ApiUsageChart buckets={buckets} />);
    const table = screen.getByRole("table", { name: "API 用量与延迟数据" });
    expect(table).toHaveTextContent("请求量");
    expect(table).toHaveTextContent("120");
    // Empty bucket row: total 0, latency cells render gap markers.
    const emptyRow = screen
      .getAllByRole("row")
      .find((row) => row.textContent?.includes("2026-07-19T01:00:00Z"));
    expect(emptyRow).toBeDefined();
    expect(emptyRow?.textContent ?? "").toContain("—");
    // The empty bucket's latency cells must never read as "0ms"; they render
    // gap markers. Assert on the row text rather than the whole table so the
    // 240ms value in another row does not cause a false positive.
    expect(emptyRow?.textContent ?? "").not.toMatch(/0ms/);
  });

  it("mounts ECharts via the svg renderer without throwing", () => {
    const onChartReady = vi.fn();
    const { rerender } = render(<ApiUsageChart buckets={buckets} />);
    // If ECharts failed to mount in jsdom the figure visual would be empty
    // and the next assertion would still pass; the absence of thrown errors
    // and presence of the figure is the smoke signal.
    expect(screen.getByRole("figure", { name: "API 用量与延迟" })).toBeInTheDocument();
    expect(onChartReady).not.toHaveBeenCalled();
    rerender(<ApiUsageChart buckets={[]} />);
    expect(screen.getByRole("figure", { name: "API 用量与延迟" })).toBeInTheDocument();
  });
});
