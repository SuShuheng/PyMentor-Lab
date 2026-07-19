import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AdminRoutes } from "./admin-routes";
import { adminSession } from "./features/auth/auth-session";

const liveAdminSession = {
  ...adminSession,
  accessToken: "admin-access",
};

const queryClient = new QueryClient({
  defaultOptions: { queries: { gcTime: 0, retry: false, staleTime: 0 } },
});

function renderAdmin(route: string) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <AdminRoutes initialSession={liveAdminSession} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("admin sidebar and topbar button wiring (FE-012)", () => {
  it("routes the 设置 sidebar tool to the settings page", async () => {
    const user = userEvent.setup();
    renderAdmin("/admin/overview");

    await user.click(screen.getByRole("button", { name: "设置" }));

    expect(await screen.findByRole("heading", { name: "管理端设置" })).toBeVisible();
  });

  it("routes the 打开控制台 sidebar tool to the operations console", async () => {
    const user = userEvent.setup();
    renderAdmin("/admin/overview");

    await user.click(screen.getByRole("button", { name: "打开控制台" }));

    expect(await screen.findByRole("heading", { name: "运行监控" })).toBeVisible();
  });

  it("opens the 系统管理员 profile dropdown and signs out to the login page", async () => {
    const user = userEvent.setup();
    renderAdmin("/admin/overview");

    const profileButton = screen.getByRole("button", { name: /系统管理员/ });
    await user.click(profileButton);

    const menu = await screen.findByRole("menu", { name: /管理员会话/ });
    // Current session info is shown inside the menu.
    expect(within(menu).getByText(/系统管理员/)).toBeInTheDocument();
    const logoutItem = within(menu).getByRole("menuitem", { name: "退出登录" });
    expect(logoutItem).toBeVisible();

    await user.click(logoutItem);

    expect(await screen.findByRole("heading", { name: "管理员登录" })).toBeVisible();
  });
});
