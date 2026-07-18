import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { StudentRoutes } from "../../student-routes";
import type { AuthApi } from "./auth-session";

const pendingApi: AuthApi = {
  login: vi.fn().mockResolvedValue({ outcome: "pending" }),
  register: vi.fn(),
  refresh: vi.fn(),
  startDemo: vi.fn(),
};

describe("student authentication flow", () => {
  it("guards student routes and exposes accessible login fields", () => {
    render(
      <MemoryRouter initialEntries={["/today"]}>
        <StudentRoutes api={pendingApi} initialSession={null} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "学号或邮箱" })).toBeVisible();
    expect(screen.getByLabelText("密码")).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "登录" })).toBeVisible();
  });

  it("renders a rejected account reason without opening protected routes", async () => {
    const rejectedApi: AuthApi = {
      ...pendingApi,
      login: vi.fn().mockResolvedValue({
        outcome: "rejected",
        reason: "学号与学校记录不一致",
      }),
    };
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <StudentRoutes api={rejectedApi} initialSession={null} />
      </MemoryRouter>,
    );

    await user.type(
      screen.getByRole("textbox", { name: "学号或邮箱" }),
      "rejected@example.edu",
    );
    await user.type(
      screen.getByLabelText("密码"),
      "correct-horse-battery-staple",
    );
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(
      await screen.findByRole("alert", { name: "账号申请未通过" }),
    ).toHaveTextContent("学号与学校记录不一致");
  });

  it("enters the student application after an approved login", async () => {
    const approvedApi: AuthApi = {
      ...pendingApi,
      login: vi.fn().mockResolvedValue({
        outcome: "authenticated",
        session: {
          accountStatus: "active",
          displayName: "林晓",
          role: "student",
          userId: "STU-2026001",
        },
      }),
    };
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <StudentRoutes api={approvedApi} initialSession={null} />
      </MemoryRouter>,
    );

    await user.type(
      screen.getByRole("textbox", { name: "学号或邮箱" }),
      "20260001",
    );
    await user.type(screen.getByLabelText("密码"), "approved-password");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(
      await screen.findByRole("heading", { name: "今日学习工作台" }),
    ).toBeVisible();
  });

  it("submits a complete registration into the pending-review state", async () => {
    const registrationApi: AuthApi = {
      ...pendingApi,
      register: vi.fn().mockResolvedValue({ outcome: "pending" }),
    };
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/register"]}>
        <StudentRoutes api={registrationApi} initialSession={null} />
      </MemoryRouter>,
    );

    await user.type(screen.getByRole("textbox", { name: "姓名" }), "陈雨");
    await user.type(screen.getByRole("textbox", { name: "学号" }), "20260008");
    await user.type(
      screen.getByRole("textbox", { name: "学校邮箱" }),
      "chenyu@example.edu",
    );
    await user.type(screen.getByLabelText("密码"), "registration-password");
    await user.click(screen.getByRole("button", { name: "提交审核" }));

    expect(
      await screen.findByRole("status", { name: "账号正在审核" }),
    ).toHaveTextContent("注册资料已提交");
    expect(registrationApi.register).toHaveBeenCalledWith({
      displayName: "陈雨",
      email: "chenyu@example.edu",
      password: "registration-password",
      studentId: "20260008",
    });
  });

  it("explains a failed refresh and lets the learner retry", async () => {
    const refreshApi: AuthApi = {
      ...pendingApi,
      refresh: vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    };
    render(
      <MemoryRouter initialEntries={["/today"]}>
        <StudentRoutes api={refreshApi} />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("alert", { name: "无法恢复登录会话" }),
    ).toHaveTextContent("会话刷新失败");
    expect(screen.getByRole("button", { name: "重试会话刷新" })).toBeVisible();
  });

  it("rejects an administrator session at the student guard", () => {
    render(
      <MemoryRouter initialEntries={["/today"]}>
        <StudentRoutes
          initialSession={{
            accountStatus: "active",
            displayName: "系统管理员",
            role: "admin",
            userId: "admin-001",
          }}
        />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("alert", { name: "当前账号不能进入学生端" }),
    ).toHaveTextContent("独立管理端登录");
  });

  it("shows the account review state instead of entering the app", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <StudentRoutes api={pendingApi} initialSession={null} />
      </MemoryRouter>,
    );

    await user.type(
      screen.getByRole("textbox", { name: "学号或邮箱" }),
      "pending@example.edu",
    );
    await user.type(
      screen.getByLabelText("密码"),
      "correct-horse-battery-staple",
    );
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(
      await screen.findByRole("status", { name: "账号正在审核" }),
    ).toHaveTextContent("管理员审核通过后即可登录");
  });

  it("offers one-click isolated demo access", async () => {
    const demoApi: AuthApi = {
      ...pendingApi,
      startDemo: vi.fn().mockResolvedValue({
        outcome: "authenticated",
        session: {
          accountStatus: "active",
          displayName: "演示访客",
          role: "demo",
          userId: "demo-guest",
        },
      }),
    };
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <StudentRoutes api={demoApi} initialSession={null} />
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("button", { name: "一键体验演示" }));

    expect(
      await screen.findByRole("heading", { name: "今日学习工作台" }),
    ).toBeVisible();
  });
});
