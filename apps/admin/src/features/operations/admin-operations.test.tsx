import { render, screen, waitFor, within } from "@testing-library/react";
import { saveServerUrl } from "@pymentor/config";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminRoutes } from "../../admin-routes";
import { adminSession } from "../auth/auth-session";

const liveAdminSession = {
  ...adminSession,
  accessToken: "admin-access",
};

const pendingRegistration = {
  created_at: "2026-07-19T02:30:00Z",
  email: "chenyu@example.edu",
  status: "PENDING",
  student_no: "S-001",
  user_id: "00000000-0000-0000-0000-000000000101",
};

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

function renderAdmin(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AdminRoutes initialSession={liveAdminSession} />
    </MemoryRouter>,
  );
}

describe("admin registration and student operations", () => {
  it("reviews pending registrations from the overview", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify([pendingRegistration]), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ACTIVE" }), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/overview");

    expect(screen.getByRole("heading", { name: "管理概览" })).toBeVisible();
    const queue = screen.getByRole("region", { name: "待审核注册" });
    expect(await within(queue).findByText("S-001")).toBeVisible();
    await user.click(within(queue).getByRole("button", { name: "批准S-001的注册" }));
    await waitFor(() =>
      expect(screen.getByRole("status", { name: "注册审核状态" })).toHaveTextContent("S-001已批准"),
    );
    expect(queue).not.toHaveTextContent("S-001");

    const listRequest = fetchMock.mock.calls[0]?.[0] as Request;
    const approveRequest = fetchMock.mock.calls[1]?.[0] as Request;
    expect(listRequest.url).toContain("/api/v1/admin/registrations/pending");
    expect(listRequest.headers.get("Authorization")).toBe("Bearer admin-access");
    expect(approveRequest.url).toBe(
      `https://api.example.test/api/v1/admin/registrations/${pendingRegistration.user_id}/approve`,
    );
    expect(approveRequest.headers.get("Idempotency-Key")).toMatch(/^registration-approved-/);
  });

  it("rejects a pending registration through the generated command", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify([pendingRegistration]), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "REJECTED" }), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/overview");

    await user.click(await screen.findByRole("button", { name: "拒绝S-001的注册" }));

    await waitFor(() =>
      expect(screen.getByRole("status", { name: "注册审核状态" })).toHaveTextContent("S-001已拒绝"),
    );
    const rejectRequest = fetchMock.mock.calls[1]?.[0] as Request;
    expect(rejectRequest.url).toBe(
      `https://api.example.test/api/v1/admin/registrations/${pendingRegistration.user_id}/reject`,
    );
    expect(rejectRequest.headers.get("Authorization")).toBe("Bearer admin-access");
    expect(rejectRequest.headers.get("Idempotency-Key")).toMatch(/^registration-rejected-/);
    await expect(rejectRequest.clone().json()).resolves.toEqual({
      reason: "Rejected from the registration review queue",
    });
  });

  it("uses server-style filtering and pagination for students", async () => {
    const user = userEvent.setup();
    renderAdmin("/admin/students");

    expect(screen.getByRole("table", { name: "学生列表" })).toHaveTextContent("林晓");
    expect(screen.getByText("第 1 / 3 页")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByText("第 2 / 3 页")).toBeVisible();
    expect(screen.getByRole("table", { name: "学生列表" })).toHaveTextContent("周宁");

    await user.type(screen.getByRole("searchbox", { name: "筛选学生" }), "2026005");
    expect(screen.getByRole("table", { name: "学生列表" })).toHaveTextContent("STU-2026005");
    expect(screen.getByText("筛选结果 1 人")).toBeVisible();
  });

  it("shows a student mastery, review, and evidence record", () => {
    renderAdmin("/admin/students/STU-2026001");

    expect(screen.getByRole("heading", { name: "林晓 · 学习详情" })).toBeVisible();
    expect(screen.getByRole("region", { name: "掌握与复测" })).toHaveTextContent("循环边界");
    expect(screen.getByRole("table", { name: "学习证据" })).toHaveTextContent("EVD-1882");
    expect(screen.getByText("正式掌握状态只允许由规则引擎写入")).toBeVisible();
  });
});

describe("admin safety and infrastructure operations", () => {
  it("exposes replay, metrics, and immutable audit views", () => {
    const replay = renderAdmin("/admin/agent-runs");
    expect(screen.getByRole("heading", { name: "执行时间线 · RUN-8F21" })).toBeVisible();
    expect(screen.getByText("profile.read · evidence.query")).toBeVisible();
    replay.unmount();

    const metrics = renderAdmin("/admin/metrics");
    expect(screen.getByRole("table", { name: "请求指标数据" })).toHaveTextContent(
      "/api/v1/tutor/stream",
    );
    expect(screen.getAllByRole("progressbar")).toHaveLength(4);
    metrics.unmount();

    renderAdmin("/admin/audit");
    expect(screen.getByRole("table", { name: "系统审计记录" })).toHaveTextContent(
      "BACKUP_VERIFIED",
    );
  });

  it("masks provider secrets and tests connectivity without revealing keys", async () => {
    const user = userEvent.setup();
    renderAdmin("/admin/providers");

    expect(screen.getByRole("table", { name: "Provider 配置" })).toHaveTextContent("••••••••7H2K");
    expect(screen.queryByText("PLAINTEXT_KEY_SHOULD_NOT_RENDER")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "测试讯飞 LLM 连通性" }));
    expect(screen.getByRole("status", { name: "Provider 测试状态" })).toHaveTextContent("连接成功");
  });

  it("renders degraded health and filterable system logs", async () => {
    const degraded = renderAdmin("/admin/health?view=degraded");
    expect(screen.getByRole("alert", { name: "服务降级" })).toHaveTextContent("图像 Provider");
    expect(screen.getByRole("list", { name: "服务健康状态" })).toHaveTextContent("Sandbox");
    degraded.unmount();

    const user = userEvent.setup();
    renderAdmin("/admin/logs");
    await user.selectOptions(screen.getByRole("combobox", { name: "日志级别" }), "ERROR");
    expect(screen.getByRole("table", { name: "系统日志" })).toHaveTextContent(
      "provider.image.timeout",
    );
    expect(screen.getByRole("table", { name: "系统日志" })).not.toHaveTextContent(
      "worker.job.started",
    );
  });

  it("requires an exact confirmation phrase for database restore", async () => {
    const user = userEvent.setup();
    renderAdmin("/admin/database");

    await user.click(screen.getByRole("button", { name: "恢复备份" }));
    expect(screen.getByRole("dialog", { name: "确认恢复数据库" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "取消恢复" }));
    expect(screen.queryByRole("dialog", { name: "确认恢复数据库" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "恢复备份" }));
    const confirmButton = screen.getByRole("button", { name: "确认恢复" });
    expect(confirmButton).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "输入确认短语" }), "RESTORE PYMENTOR");
    expect(confirmButton).toBeEnabled();
    await user.click(confirmButton);
    expect(screen.getByRole("status", { name: "数据库操作状态" })).toHaveTextContent(
      "恢复任务已安全入队",
    );
  });

  it("approves and rejects reviewed resource versions explicitly", async () => {
    const user = userEvent.setup();
    renderAdmin("/admin/resources");

    await user.click(screen.getByRole("button", { name: "批准资源 RES-102" }));
    expect(screen.getByRole("status", { name: "资源审核状态" })).toHaveTextContent(
      "RES-102 已批准发布",
    );

    await user.click(screen.getByRole("button", { name: "拒绝资源 RES-103" }));
    const dialog = screen.getByRole("dialog", { name: "拒绝资源 RES-103" });
    await user.type(within(dialog).getByRole("textbox", { name: "拒绝原因" }), "来源映射不完整");
    await user.click(within(dialog).getByRole("button", { name: "确认拒绝" }));
    expect(screen.getByRole("status", { name: "资源审核状态" })).toHaveTextContent(
      "RES-103 已拒绝",
    );
  });
});
