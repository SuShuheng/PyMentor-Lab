import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts-for-react";
import type { ApiUsageBucket } from "./admin-metrics-types";
import { ChartFrame } from "./chart-frame";
import { monochromeAxis, monochromePalette, monochromeSeries, svgRendererOpts } from "./theme";

export interface ApiUsageChartProps {
  buckets: readonly ApiUsageBucket[];
  title?: string;
  description?: string;
}

/**
 * Build the ECharts option for the API-usage chart. Exported separately so unit
 * tests can assert on the option (series, gap handling for `null` p50/p95)
 * without rendering pixels.
 *
 * Per BE-028, `p50`/`p95` are `null` on empty buckets. We pass the raw `null`
 * values through to ECharts (NOT `0`) so the latency lines render as gaps —
 * an empty bucket must never be read as "0 ms latency".
 */
export function buildApiUsageOption(buckets: readonly ApiUsageBucket[]): EChartsOption {
  const labels = buckets.map((bucket) => bucket.bucket_start);
  const totals = buckets.map((bucket) => bucket.total);
  const p50 = buckets.map((bucket) => bucket.p50);
  const p95 = buckets.map((bucket) => bucket.p95);

  return {
    backgroundColor: monochromePalette.surface,
    color: monochromeSeries,
    grid: { left: 48, right: 48, top: 40, bottom: 56, containLabel: true },
    legend: {
      data: ["请求量", "P50 延迟", "P95 延迟"],
      top: 8,
      textStyle: { color: monochromePalette.steel, fontSize: 11 },
    },
    tooltip: { trigger: "axis" },
    xAxis: {
      type: "category",
      data: labels,
      ...monochromeAxis,
    },
    yAxis: [
      {
        type: "value",
        name: "请求量",
        nameTextStyle: { color: monochromePalette.steel, fontSize: 10 },
        ...monochromeAxis,
      },
      {
        type: "value",
        name: "延迟 (ms)",
        nameTextStyle: { color: monochromePalette.steel, fontSize: 10 },
        ...monochromeAxis,
      },
    ],
    series: [
      {
        name: "请求量",
        type: "bar",
        data: totals,
        barMaxWidth: 28,
        itemStyle: { color: monochromePalette.ash },
      },
      {
        name: "P50 延迟",
        type: "line",
        yAxisIndex: 1,
        data: p50,
        smooth: false,
        symbol: "circle",
        symbolSize: 6,
        connectNulls: false,
        lineStyle: { color: monochromePalette.graphite, width: 2 },
        itemStyle: { color: monochromePalette.graphite },
      },
      {
        name: "P95 延迟",
        type: "line",
        yAxisIndex: 1,
        data: p95,
        smooth: false,
        symbol: "circle",
        symbolSize: 7,
        connectNulls: false,
        lineStyle: { color: monochromePalette.ink, width: 2.5 },
        itemStyle: { color: monochromePalette.ink },
      },
    ],
  };
}

/**
 * API usage chart: volume bars (left axis) + P50/P95 latency lines (right
 * axis). Null latency buckets render as gaps, not zeros. Wrapped in
 * `ChartFrame` so the underlying bucket table is exposed to assistive tech.
 */
export function ApiUsageChart({
  buckets,
  title = "API 用量与延迟",
  description = "按时间桶聚合的请求量与 P50/P95 延迟；空桶的延迟渲染为缺口而非零值",
}: ApiUsageChartProps) {
  const option = buildApiUsageOption(buckets);
  const rows = buckets.map((bucket) => [
    bucket.bucket_start,
    String(bucket.total),
    bucket.p50 === null ? "—" : `${bucket.p50}ms`,
    bucket.p95 === null ? "—" : `${bucket.p95}ms`,
    `${(bucket.error_rate * 100).toFixed(1)}%`,
    `${(bucket.throttle_rate * 100).toFixed(1)}%`,
  ]);

  return (
    <ChartFrame
      columns={["时间桶", "请求量", "P50", "P95", "错误率", "限流率"]}
      description={description}
      rows={rows}
      title={title}
    >
      <ReactECharts
        aria-hidden="true"
        opts={svgRendererOpts}
        option={option}
        style={{ width: "100%", height: 280 }}
      />
    </ChartFrame>
  );
}
