import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { StudentRoutes } from "../../student-routes";
import { studentSession } from "../auth/auth-session";

beforeEach(() => window.localStorage.clear());

describe("conversational onboarding", () => {
  it("advances an explicit, recoverable diagnosis conversation", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/onboarding"]}>
        <StudentRoutes initialSession={studentSession} />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", { name: "建立你的学习画像" }),
    ).toBeVisible();
    expect(
      screen.getByRole("progressbar", { name: "画像构建进度" }),
    ).toHaveAttribute("aria-valuenow", "1");
    expect(screen.getByRole("status", { name: "对话进度" })).toHaveTextContent(
      "第 1 步，共 5 步",
    );

    await user.click(screen.getByRole("button", { name: "有一点基础" }));

    expect(screen.getByRole("status", { name: "对话进度" })).toHaveTextContent(
      "第 2 步，共 5 步",
    );
    expect(window.localStorage.getItem("pymentor.onboardingStep")).toBe("1");
  });

  it("keeps reconnect and incomplete-diagnosis states actionable", () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={["/onboarding?view=reconnecting"]}>
        <StudentRoutes initialSession={studentSession} />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("alert", { name: "正在重新连接" }),
    ).toHaveTextContent("已保留当前对话进度");
    expect(screen.getByRole("button", { name: "立即重连" })).toBeVisible();

    unmount();
    render(
      <MemoryRouter initialEntries={["/onboarding?view=incomplete"]}>
        <StudentRoutes initialSession={studentSession} />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("alert", { name: "诊断尚未完成" }),
    ).toHaveTextContent("不会生成正式画像版本");
  });
});

describe("evidence-linked profile", () => {
  it("shows all eight dimensions, node summaries and profile version", () => {
    render(
      <MemoryRouter initialEntries={["/growth/profile"]}>
        <StudentRoutes initialSession={studentSession} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("figure", { name: "八维能力画像" })).toBeVisible();
    for (const dimension of [
      "概念知识掌握",
      "代码执行模型",
      "编程实现能力",
      "问题分解与算法表达能力",
      "调试与错误定位能力",
      "测试与边界意识",
      "迁移与综合应用能力",
      "独立完成度与支架需求",
    ]) {
      expect(screen.getByRole("rowheader", { name: dimension })).toBeVisible();
    }
    expect(screen.getByRole("heading", { name: "画像版本 v3" })).toBeVisible();
    expect(screen.getByText("按知识节点聚合")).toBeVisible();
  });

  it("progressively discloses evidence and submits a dispute", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/growth/profile"]}>
        <StudentRoutes initialSession={studentSession} />
      </MemoryRouter>,
    );

    expect(
      screen.queryByRole("region", { name: "画像证据" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看画像证据" }));
    expect(screen.getByRole("region", { name: "画像证据" })).toHaveTextContent(
      "EVD-2048",
    );

    await user.click(screen.getByRole("button", { name: "对画像提出异议" }));
    expect(screen.getByRole("dialog", { name: "提交画像异议" })).toBeVisible();
    await user.type(
      screen.getByRole("textbox", { name: "异议说明" }),
      "这次循环练习未计入画像。 ",
    );
    await user.click(screen.getByRole("button", { name: "提交异议" }));

    expect(screen.getByRole("status", { name: "异议状态" })).toHaveTextContent(
      "异议已提交",
    );
  });
});
