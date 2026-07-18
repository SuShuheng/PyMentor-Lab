import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AdminRoutes } from "./admin-routes";
import { adminSession, studentSession } from "./features/auth/auth-session";

describe("admin application shell", () => {
  it("routes to Agent replay and marks its navigation item as current", () => {
    render(
      <MemoryRouter initialEntries={["/admin/agent-runs"]}>
        <AdminRoutes initialSession={adminSession} />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", { name: "Agent 调用回放" }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Agent 调用回放" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("announces a loading state on the health route", () => {
    render(
      <MemoryRouter initialEntries={["/admin/health?view=loading"]}>
        <AdminRoutes initialSession={adminSession} />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("status", { name: "加载系统健康状态" }),
    ).toHaveTextContent("正在检查 API、Worker、沙箱与数据服务");
  });

  it("rejects a student session at the independent admin guard", () => {
    render(
      <MemoryRouter initialEntries={["/admin/overview"]}>
        <AdminRoutes initialSession={studentSession} />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("alert", { name: "无权访问管理端" }),
    ).toHaveTextContent("当前学生账号没有管理员权限");
  });

  it("redirects an anonymous visitor to the accessible admin login", () => {
    render(
      <MemoryRouter initialEntries={["/admin/overview"]}>
        <AdminRoutes initialSession={null} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "管理员登录" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "管理员账号" })).toBeVisible();
    expect(screen.getByLabelText("密码")).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "登录管理端" })).toBeVisible();
  });
});
