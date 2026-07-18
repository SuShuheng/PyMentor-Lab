import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChartFrame } from "./chart-frame";

describe("ChartFrame", () => {
  it("provides a labelled figure and equivalent data table", () => {
    render(
      <ChartFrame
        columns={["维度", "得分"]}
        description="展示当前八维能力得分"
        rows={[
          ["代码能力", "72"],
          ["知识理解", "68"],
        ]}
        title="八维成长总览"
      >
        <div>chart canvas</div>
      </ChartFrame>,
    );

    expect(
      screen.getByRole("figure", { name: "八维成长总览" }),
    ).toHaveTextContent("展示当前八维能力得分");
    expect(
      screen.getByRole("table", { name: "八维成长总览数据" }),
    ).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "维度" })).toBeVisible();
    expect(screen.getByRole("rowheader", { name: "代码能力" })).toBeVisible();
  });
});
