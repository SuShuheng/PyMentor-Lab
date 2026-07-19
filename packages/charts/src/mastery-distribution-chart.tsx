import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts-for-react";
import { MASTERY_STATUSES, type MasteryStatus } from "./admin-metrics-types";
import { ChartFrame } from "./chart-frame";
import { monochromeAxis, monochromePalette, monochromeSeries, svgRendererOpts } from "./theme";

/** Human-readable Chinese labels for each mastery status (chart legend + table). */
export const MASTERY_STATUS_LABELS: Record<MasteryStatus, string> = {
  UNSEEN: "未接触",
  LEARNING: "学习中",
  PASSED_WITH_HELP: "辅助通过",
  INITIAL_MASTERY: "初步掌握",
  STABLE_MASTERY: "稳定掌握",
  REVIEW_REQUIRED: "待复测",
};

export interface MasteryDistributionChartProps {
  counts: Partial<Record<MasteryStatus, number>>;
  title?: string;
  description?: string;
}

/**
 * Build the ECharts option for the mastery distribution stacked bar. Exported
 * separately for unit testing. Each of the six statuses becomes one stacked
 * segment; the single category column ("掌握分布") makes it read as a
 * composition bar.
 */
export function buildMasteryDistributionOption(
  counts: Partial<Record<MasteryStatus, number>>,
): EChartsOption {
  const series = MASTERY_STATUSES.map((status, index) => ({
    name: MASTERY_STATUS_LABELS[status],
    type: "bar" as const,
    stack: "mastery",
    barMaxWidth: 56,
    itemStyle: {
      color: monochromeSeries[index] ?? monochromePalette.ash,
    },
    emphasis: { focus: "series" as const },
    data: [counts[status] ?? 0],
  }));

  return {
    backgroundColor: monochromePalette.surface,
    color: monochromeSeries,
    grid: { left: 48, right: 32, top: 40, bottom: 32, containLabel: true },
    legend: {
      data: MASTERY_STATUSES.map((status) => MASTERY_STATUS_LABELS[status]),
      top: 8,
      textStyle: { color: monochromePalette.steel, fontSize: 11 },
    },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: {
      type: "category",
      data: ["掌握分布"],
      ...monochromeAxis,
    },
    yAxis: {
      type: "value",
      name: "学生数",
      nameTextStyle: { color: monochromePalette.steel, fontSize: 10 },
      ...monochromeAxis,
    },
    series,
  };
}

/**
 * Mastery distribution chart: a single stacked composition bar across the six
 * mastery statuses. The accompanying table (via `ChartFrame`) lists each
 * status count for assistive technology.
 */
export function MasteryDistributionChart({
  counts,
  title = "掌握状态分布",
  description = "按六种掌握状态聚合的学生分布；正式状态由规则引擎写入",
}: MasteryDistributionChartProps) {
  const option = buildMasteryDistributionOption(counts);
  const total = MASTERY_STATUSES.reduce((sum, status) => sum + (counts[status] ?? 0), 0);
  const rows = MASTERY_STATUSES.map((status) => {
    const value = counts[status] ?? 0;
    const share = total > 0 ? `${((value / total) * 100).toFixed(1)}%` : "0.0%";
    return [MASTERY_STATUS_LABELS[status], String(value), share];
  });

  return (
    <ChartFrame
      columns={["状态", "学生数", "占比"]}
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
