import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts-for-react";
import type { AgentTimelinePoint } from "./admin-metrics-types";
import { ChartFrame } from "./chart-frame";
import { monochromeAxis, monochromePalette, monochromeSeries, svgRendererOpts } from "./theme";

export interface AgentTimelineChartProps {
  points: readonly AgentTimelinePoint[];
  title?: string;
  description?: string;
}

/** Status → monochrome shade. Deterministic so the legend stays stable. */
function statusColor(status: string, fallback: boolean): string {
  if (fallback) return monochromePalette.mist;
  const normalized = status.toUpperCase();
  const map: Record<string, string> = {
    SUCCEEDED: monochromePalette.ink,
    RUNNING: monochromePalette.graphite,
    FAILED: monochromePalette.silver,
    CANCELLED: monochromePalette.ash,
  };
  return map[normalized] ?? monochromePalette.steel;
}

/**
 * Build the ECharts option for the agent timeline Gantt. Exported separately
 * for unit testing.
 *
 * Each run is one custom-rendered bar (`series.type: 'custom'`) whose body
 * spans `[started_at, ended_at]` on a time xAxis. Runs that are still in
 * flight (`ended_at === null`) extend to the chart's right edge so they remain
 * visible. `fallback` runs are rendered with a hatched/mist fill so operators
 * can spot degradation at a glance.
 */
export function buildAgentTimelineOption(points: readonly AgentTimelinePoint[]): EChartsOption {
  if (points.length === 0) {
    return {
      backgroundColor: monochromePalette.surface,
      xAxis: { type: "time", ...monochromeAxis },
      yAxis: { type: "category", data: [], ...monochromeAxis },
      series: [{ type: "custom", renderItem: () => ({ type: "group" }), data: [] }],
    };
  }

  const reversed = [...points].reverse();
  const categories = reversed.map((point) => point.run_id);

  const renderItem = (
    _params: unknown,
    api: {
      value: (index: number) => unknown;
      coord: (value: (number | string)[]) => [number, number];
      size: (value: (number | string)[]) => [number, number];
    },
  ) => {
    const categoryIndex = Number(api.value(0));
    const start = Number(api.value(1));
    const end = Number(api.value(2));
    const status = String(api.value(3));
    const fallback = Boolean(api.value(4));
    const startCoord = api.coord([start, categoryIndex]);
    const endCoord = api.coord([end, categoryIndex]);
    const height = 14;
    return {
      type: "rect",
      shape: {
        x: startCoord[0],
        y: startCoord[1] - height / 2,
        width: Math.max(2, endCoord[0] - startCoord[0]),
        height,
        r: 2,
      },
      style: {
        fill: statusColor(status, fallback),
        stroke: fallback ? monochromePalette.ink : monochromePalette.surface,
        lineWidth: fallback ? 1 : 0,
        lineDash: fallback ? [3, 2] : undefined,
      },
    };
  };

  const now = Date.now();
  const seriesData = reversed.map((point, index) => {
    const start = new Date(point.started_at).getTime();
    const endRaw = point.ended_at ? new Date(point.ended_at).getTime() : null;
    const end = endRaw ?? Math.max(now, start + 60_000);
    return {
      value: [index, start, end, point.status, point.fallback],
      itemStyle: { color: statusColor(point.status, point.fallback) },
    };
  });

  return {
    backgroundColor: monochromePalette.surface,
    color: monochromeSeries,
    grid: { left: 96, right: 32, top: 24, bottom: 48, containLabel: true },
    tooltip: {
      formatter: (payload: unknown) => {
        const item = payload as { value?: (string | number | boolean)[] };
        const value = item.value ?? [];
        const idx = Number(value[0]);
        const point = reversed[idx];
        if (!point) return "";
        const latency = point.latency_ms === null ? "—" : `${point.latency_ms}ms`;
        return [
          `<strong>${point.run_id}</strong>`,
          `route: ${point.route}`,
          `status: ${point.status}${point.fallback ? " (fallback)" : ""}`,
          `latency: ${latency}`,
        ].join("<br/>");
      },
    },
    xAxis: {
      type: "time",
      ...monochromeAxis,
    },
    yAxis: {
      type: "category",
      data: categories,
      ...monochromeAxis,
      axisLabel: {
        ...monochromeAxis.axisLabel,
        formatter: (value: string) => (value.length > 12 ? `${value.slice(0, 10)}…` : value),
      },
    },
    series: [
      {
        type: "custom",
        renderItem,
        encode: { x: [1, 2], y: 0 },
        data: seriesData,
      },
    ],
  };
}

/**
 * Agent execution timeline (Gantt-style): each run is a horizontal bar on a
 * time axis, shaded by status, with fallback runs rendered as a mist outline.
 * The companion table (via `ChartFrame`) exposes route / status / fallback /
 * latency for assistive technology.
 */
export function AgentTimelineChart({
  points,
  title = "Agent 执行时间线",
  description = "按起始与结束时间排列的 Agent 运行；fallback 运行以描边标识",
}: AgentTimelineChartProps) {
  const option = buildAgentTimelineOption(points);
  const rows = points.map((point) => [
    point.run_id,
    point.route,
    point.status,
    point.fallback ? "是" : "否",
    point.latency_ms === null ? "—" : `${point.latency_ms}ms`,
    new Date(point.started_at).toLocaleString("zh-CN"),
  ]);

  return (
    <ChartFrame
      columns={["Run", "Route", "状态", "Fallback", "延迟", "开始时间"]}
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
