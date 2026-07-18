import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PageTransition, Skeleton } from "./motion";

describe("shared motion primitives", () => {
  it("removes transition duration when reduced motion is requested", () => {
    render(
      <PageTransition reducedMotion>
        <p>今日学习内容</p>
      </PageTransition>,
    );

    expect(screen.getByText("今日学习内容").parentElement).toHaveAttribute(
      "data-transition-duration",
      "0",
    );
  });

  it("announces a labelled skeleton without exposing decorative bars", () => {
    render(<Skeleton label="正在生成知识结构卡" lines={3} />);

    expect(
      screen.getByRole("status", { name: "正在生成知识结构卡" }),
    ).toBeVisible();
    expect(screen.getAllByTestId("skeleton-line")).toHaveLength(3);
  });
});
