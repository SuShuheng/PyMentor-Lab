import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StatePanel } from "./state-panel";

describe("StatePanel", () => {
  it("announces loading without presenting it as an error", () => {
    render(
      <StatePanel
        description="正在同步你的学习计划"
        state="loading"
        title="加载今日任务"
      />,
    );

    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("offers an actionable retry for transient failures", async () => {
    const onAction = vi.fn();
    const user = userEvent.setup();
    render(
      <StatePanel
        actionLabel="重新连接"
        description="请检查网络后重试"
        onAction={onAction}
        state="offline"
        title="当前处于离线状态"
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("当前处于离线状态");
    await user.click(screen.getByRole("button", { name: "重新连接" }));
    expect(onAction).toHaveBeenCalledOnce();
  });
});
