import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { StudentRoutes } from "../../student-routes";
import { studentSession } from "../auth/auth-session";

function renderRoute(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <StudentRoutes initialSession={studentSession} />
    </MemoryRouter>,
  );
}

describe("Today learning plan", () => {
  it("prioritizes a due review and explains recommendation, timing and progress", () => {
    renderRoute("/today");

    const dueReview = screen.getByRole("article", {
      name: "到期复测：循环边界",
    });
    expect(dueReview).toHaveAttribute("data-priority", "1");
    expect(dueReview).toHaveTextContent("今天到期");
    expect(dueReview).toHaveTextContent("依据 EVD-1882");
    expect(
      within(dueReview).getByRole("button", { name: "开始复测" }),
    ).toBeVisible();
    expect(
      screen.getByRole("progressbar", { name: "今日任务完成度" }),
    ).toHaveAttribute("aria-valuenow", "33");
  });

  it("marks a completed task and updates today progress", async () => {
    const user = userEvent.setup();
    renderRoute("/today");

    const dueReview = screen.getByRole("article", {
      name: "到期复测：循环边界",
    });
    await user.click(
      within(dueReview).getByRole("button", { name: "开始复测" }),
    );

    expect(
      within(dueReview).getByRole("button", { name: "已完成" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("progressbar", { name: "今日任务完成度" }),
    ).toHaveAttribute("aria-valuenow", "67");
  });

  it("keeps empty and delayed-resource states explicit", () => {
    const { unmount } = renderRoute("/today?view=empty");
    expect(
      screen.getByRole("status", { name: "今天还没有学习任务" }),
    ).toBeVisible();

    unmount();
    renderRoute("/today?view=delayed");
    expect(
      screen.getByRole("status", { name: "资源仍在生成" }),
    ).toHaveTextContent("可先使用文本讲解与代码例题");
    expect(
      screen.getByRole("button", { name: "使用可用资源继续" }),
    ).toBeVisible();

    unmount();
    renderRoute("/today?view=error");
    expect(
      screen.getByRole("alert", { name: "无法加载今日任务" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "重试" })).toBeVisible();
  });

  it("can pause and reschedule without silently changing formal task state", async () => {
    const user = userEvent.setup();
    renderRoute("/today");

    const headingActions = screen.getByRole("group", {
      name: "今日计划操作",
    });
    expect(
      within(headingActions).getByRole("link", { name: "学习资源" }),
    ).toHaveClass("today-heading-action");
    expect(
      within(headingActions).getByRole("link", { name: "智能辅导" }),
    ).toHaveClass("today-heading-action");

    await user.click(screen.getByRole("button", { name: "暂停今日计划" }));
    expect(screen.getByRole("status", { name: "计划状态" })).toHaveTextContent(
      "今日计划已暂停",
    );

    await user.click(screen.getByRole("button", { name: "重新安排任务" }));
    expect(
      screen.getByRole("dialog", { name: "重新安排学习任务" }),
    ).toBeVisible();
    await user.selectOptions(
      screen.getByRole("combobox", { name: "新的学习时间" }),
      "tomorrow-evening",
    );
    await user.click(screen.getByRole("button", { name: "确认重新安排" }));
    expect(screen.getByRole("status", { name: "计划状态" })).toHaveTextContent(
      "已安排到明天 19:30",
    );
  });
});

describe("Map and Growth", () => {
  it("shows validated path changes and server-owned mastery states", () => {
    renderRoute("/map");

    expect(
      screen.getByRole("status", { name: "学习路径已调整" }),
    ).toHaveTextContent("最近两次边界测试");
    expect(
      screen.getByRole("list", { name: "当前学习路径" }),
    ).toHaveTextContent("函数基础");
    expect(screen.getAllByText("STABLE_MASTERY · 稳定掌握")).toHaveLength(2);
    expect(screen.getByText("LEARNING · 学习中")).toBeVisible();
  });

  it("submits a delayed-review request without claiming mastery", async () => {
    const user = userEvent.setup();
    renderRoute("/growth");

    expect(screen.getByRole("heading", { name: "我的成长" })).toBeVisible();
    expect(screen.getByText("初步掌握 ≠ 稳定掌握")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "申请循环边界复测" }));
    expect(
      screen.getByRole("status", { name: "复测申请状态" }),
    ).toHaveTextContent("复测申请已提交");
  });

  it("announces permission failures instead of rendering stale task data", () => {
    renderRoute("/today?view=permission");

    expect(
      screen.getByRole("alert", { name: "无权访问此任务" }),
    ).toHaveTextContent("课程权限可能已变更");
  });
});
