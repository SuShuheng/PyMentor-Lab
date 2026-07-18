import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { StudentRoutes } from "../../student-routes";
import { studentSession } from "../auth/auth-session";

function renderLab(route = "/lab") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <StudentRoutes initialSession={studentSession} />
    </MemoryRouter>,
  );
}

describe("controlled notebook", () => {
  it("runs code through an explicit lifecycle and reports visible/hidden tests", async () => {
    const user = userEvent.setup();
    renderLab();

    expect(
      (
        screen.getByRole("textbox", {
          name: "Python 代码编辑器",
        }) as HTMLTextAreaElement
      ).value,
    ).toContain("def sum_even");
    await user.click(screen.getByRole("button", { name: "运行代码" }));
    expect(screen.getByRole("status", { name: "运行状态" })).toHaveTextContent(
      "正在安全沙箱中运行",
    );

    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: "运行状态" }),
      ).toHaveTextContent("运行完成"),
    );
    expect(
      screen.getByRole("list", { name: "可见测试结果" }),
    ).toHaveTextContent("3 / 3 通过");
    expect(
      screen.getByText("隐藏测试：2 / 2 通过（测试内容不公开）"),
    ).toBeVisible();
    expect(screen.getByText(/测试通过不等于知识已掌握/)).toBeVisible();
  });

  it("cancels a running job without showing a false success", async () => {
    const user = userEvent.setup();
    renderLab();

    await user.click(screen.getByRole("button", { name: "运行代码" }));
    await user.click(screen.getByRole("button", { name: "取消运行" }));

    expect(screen.getByRole("status", { name: "运行状态" })).toHaveTextContent(
      "运行已取消",
    );
    expect(
      screen.queryByText("隐藏测试：2 / 2 通过（测试内容不公开）"),
    ).not.toBeInTheDocument();
  });

  it("bounds long output and distinguishes user code from platform failures", () => {
    const { unmount } = renderLab("/lab?view=long-output");
    expect(screen.getByRole("log", { name: "程序输出" })).toHaveTextContent(
      "输出已截断",
    );

    unmount();
    renderLab("/lab?view=user-error");
    expect(
      screen.getByRole("alert", { name: "代码运行错误" }),
    ).toHaveTextContent("IndexError");

    unmount();
    renderLab("/lab?view=platform-error");
    expect(
      screen.getByRole("alert", { name: "平台运行失败" }),
    ).toHaveTextContent("不会计入学习证据");
  });

  it("reveals bounded hints and keeps revision history", async () => {
    const user = userEvent.setup();
    renderLab();

    expect(screen.getByText("提示预算 0 / 3")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "使用一级提示" }));
    expect(screen.getByRole("status", { name: "提示内容" })).toHaveTextContent(
      "先检查循环范围",
    );
    expect(screen.getByText("提示预算 1 / 3")).toBeVisible();
    expect(
      screen.getByRole("list", { name: "代码修订历史" }),
    ).toHaveTextContent("v3 · 当前版本");
  });

  it("submits only the latest successfully tested revision", async () => {
    const user = userEvent.setup();
    renderLab();

    const submitButton = screen.getByRole("button", { name: "提交本次练习" });
    expect(submitButton).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "运行代码" }));
    await waitFor(() => expect(submitButton).toBeEnabled());
    await user.click(submitButton);

    expect(screen.getByRole("status", { name: "提交状态" })).toHaveTextContent(
      "正在提交已测试版本",
    );
    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: "提交状态" }),
      ).toHaveTextContent("提交成功 · SUB-LOOP-2407"),
    );
    expect(screen.getByText(/提交不会直接改变掌握状态/)).toBeVisible();
  });
});

describe("trace playback", () => {
  it("steps through deterministic frames and records a prediction", async () => {
    const user = userEvent.setup();
    renderLab("/lab/trace");

    expect(screen.getByRole("heading", { name: "代码执行轨迹" })).toBeVisible();
    expect(
      screen.getByRole("status", { name: "当前轨迹步骤" }),
    ).toHaveTextContent("步骤 1 / 4");
    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(
      screen.getByRole("status", { name: "当前轨迹步骤" }),
    ).toHaveTextContent("步骤 2 / 4");

    await user.click(screen.getByRole("button", { name: "播放轨迹" }));
    expect(screen.getByRole("button", { name: "暂停播放" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "暂停播放" }));
    expect(screen.getByRole("button", { name: "播放轨迹" })).toBeVisible();

    await user.click(screen.getByRole("radio", { name: "i 将变为 2" }));
    await user.click(screen.getByRole("button", { name: "提交关键帧预测" }));
    expect(
      screen.getByRole("status", { name: "预测证据状态" }),
    ).toHaveTextContent("预测已记录为证据 EVD-TRACE-302");
  });
});
