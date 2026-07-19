import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  MasteryDistributionChart,
  buildMasteryDistributionOption,
} from "./mastery-distribution-chart";

const counts = {
  UNSEEN: 12,
  LEARNING: 34,
  PASSED_WITH_HELP: 8,
  INITIAL_MASTERY: 21,
  STABLE_MASTERY: 40,
  REVIEW_REQUIRED: 5,
} as const;

describe("MasteryDistributionChart option", () => {
  it("builds one stacked segment per mastery status in canonical order", () => {
    const option = buildMasteryDistributionOption(counts);
    const series = option.series as Array<{
      name: string;
      type: string;
      stack: string;
      data: number[];
    }>;
    expect(series.map((item) => item.name)).toEqual([
      "未接触",
      "学习中",
      "辅助通过",
      "初步掌握",
      "稳定掌握",
      "待复测",
    ]);
    expect(series.every((item) => item.type === "bar")).toBe(true);
    expect(series.every((item) => item.stack === "mastery")).toBe(true);
    expect(series[0]?.data).toEqual([12]);
    expect(series[4]?.data).toEqual([40]);
  });

  it("treats missing statuses as zero instead of dropping the segment", () => {
    const option = buildMasteryDistributionOption({ LEARNING: 7 });
    const series = option.series as Array<{ name: string; data: number[] }>;
    expect(series).toHaveLength(6);
    const learning = series.find((item) => item.name === "学习中");
    const unseen = series.find((item) => item.name === "未接触");
    expect(learning?.data).toEqual([7]);
    expect(unseen?.data).toEqual([0]);
  });
});

describe("MasteryDistributionChart render", () => {
  it("lists every status with its count and share", () => {
    render(<MasteryDistributionChart counts={counts} />);
    const table = screen.getByRole("table", { name: "掌握状态分布数据" });
    expect(table).toHaveTextContent("稳定掌握");
    expect(table).toHaveTextContent("40");
    // 40 / 120 = 33.3%
    expect(table).toHaveTextContent("33.3%");
    expect(table).toHaveTextContent("待复测");
  });
});
