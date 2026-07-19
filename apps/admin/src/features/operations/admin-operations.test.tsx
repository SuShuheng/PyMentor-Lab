import { render, screen, waitFor, within } from "@testing-library/react";
import { saveServerUrl } from "@pymentor/config";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { gcTime: 0, retry: false, staleTime: 0 },
    },
  });
}

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

function renderAdmin(route: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[route]}>
        <AdminRoutes initialSession={liveAdminSession} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("admin registration and student operations", () => {
  it("loads a paginated student and its profile, progress, and evidence from the API", async () => {
    saveServerUrl("https://api.example.test");
    const studentId = "00000000-0000-0000-0000-000000000401";
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.url.includes("/api/v1/admin/students?") || request.url.endsWith("/students")) {
        return new Response(
          JSON.stringify({
            items: [
              {
                completed_tasks: 9,
                created_at: "2026-07-19T02:30:00Z",
                display_name: "Live Student",
                due_reviews: 2,
                email: "live@example.edu",
                id: studentId,
                profile_version: 4,
                status: "ACTIVE",
                student_no: "LIVE-401",
              },
            ],
            page: { number: 1, size: 2, total_items: 1, total_pages: 1 },
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.url.endsWith(`/students/${studentId}/profile`)) {
        return new Response(
          JSON.stringify({
            created_at: "2026-07-19T02:30:00Z",
            dimensions: [
              {
                confidence: 0.9,
                dimension: "live_dimension",
                scope_key: "course:live",
                score: 0.8,
                support_level: 3,
              },
            ],
            student_id: studentId,
            version: 4,
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.url.endsWith(`/students/${studentId}/progress`)) {
        return new Response(
          JSON.stringify({
            completed_tasks: 9,
            current_node_id: "node-live",
            current_path_id: "path-live",
            due_reviews: 2,
            last_active_at: "2026-07-19T02:30:00Z",
            mastery_counts: { INITIAL_MASTERY: 3, STABLE_MASTERY: 6 },
            student_id: studentId,
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.url.includes(`/students/${studentId}/evidence`)) {
        return new Response(
          JSON.stringify({
            items: [
              {
                course_id: null,
                created_at: "2026-07-19T02:30:00Z",
                event_id: "EVD-LIVE-401",
                event_type: "ASSESSMENT_RECORDED",
                evidence_confidence: 0.95,
                id: "00000000-0000-0000-0000-000000000402",
                node_id: "node-live",
                task_id: "task-live",
                trace_id: "trace-live-401",
              },
            ],
            page: { number: 1, size: 20, total_items: 1, total_pages: 1 },
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      throw new Error(`Unexpected request: ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const list = renderAdmin("/admin/students");
    expect(await screen.findByText("Live Student")).toBeVisible();
    expect(screen.getByText("LIVE-401")).toBeVisible();
    list.unmount();

    renderAdmin(`/admin/students/${studentId}`);
    expect(await screen.findByText("live_dimension")).toBeVisible();
    expect(screen.getByText("EVD-LIVE-401")).toBeVisible();
    expect(screen.getAllByText("node-live")[0]).toBeVisible();

    expect(fetchMock).toHaveBeenCalledTimes(4);
    for (const [request] of fetchMock.mock.calls) {
      expect((request as Request).headers.get("Authorization")).toBe("Bearer admin-access");
    }
  });

  it("reviews pending registrations from the overview", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.url.includes("/api/v1/admin/registrations/pending")) {
        return new Response(JSON.stringify([pendingRegistration]), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      if (request.url.endsWith("/api/v1/admin/overview")) {
        return new Response(
          JSON.stringify({
            active_students: 1,
            pending_registrations: 1,
            resource_reviews: 0,
            due_reviews: 0,
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.url.endsWith(`/registrations/${pendingRegistration.user_id}/approve`)) {
        return new Response(JSON.stringify({ status: "ACTIVE" }), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      throw new Error(`Unexpected request: ${request.url}`);
    });
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

    const listRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find((request) => request.url.includes("/api/v1/admin/registrations/pending"));
    expect(listRequest?.headers.get("Authorization")).toBe("Bearer admin-access");
    const approveRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find((request) =>
        request.url.endsWith(
          `/api/v1/admin/registrations/${pendingRegistration.user_id}/approve`,
        ),
      );
    expect(approveRequest?.url).toBe(
      `https://api.example.test/api/v1/admin/registrations/${pendingRegistration.user_id}/approve`,
    );
    expect(approveRequest?.headers.get("Idempotency-Key")).toMatch(/^registration-approved-/);
  });

  it("rejects a pending registration through the generated command", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.url.includes("/api/v1/admin/registrations/pending")) {
        return new Response(JSON.stringify([pendingRegistration]), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      if (request.url.endsWith("/api/v1/admin/overview")) {
        return new Response(
          JSON.stringify({
            active_students: 1,
            pending_registrations: 1,
            resource_reviews: 0,
            due_reviews: 0,
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.url.endsWith(`/registrations/${pendingRegistration.user_id}/reject`)) {
        return new Response(JSON.stringify({ status: "REJECTED" }), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      throw new Error(`Unexpected request: ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/overview");

    await user.click(await screen.findByRole("button", { name: "拒绝S-001的注册" }));

    await waitFor(() =>
      expect(screen.getByRole("status", { name: "注册审核状态" })).toHaveTextContent("S-001已拒绝"),
    );
    const rejectRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find((request) =>
        request.url.endsWith(
          `/api/v1/admin/registrations/${pendingRegistration.user_id}/reject`,
        ),
      );
    expect(rejectRequest?.url).toBe(
      `https://api.example.test/api/v1/admin/registrations/${pendingRegistration.user_id}/reject`,
    );
    expect(rejectRequest?.headers.get("Authorization")).toBe("Bearer admin-access");
    expect(rejectRequest?.headers.get("Idempotency-Key")).toMatch(/^registration-rejected-/);
    await expect(rejectRequest?.clone().json()).resolves.toEqual({
      reason: "Rejected from the registration review queue",
    });
  });
});

describe("admin safety and infrastructure operations", () => {
  it("loads resource review evidence and a redacted agent replay from the API", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.url.includes("/api/v1/admin/resources/reviews")) {
        return new Response(
          JSON.stringify({
            items: [
              {
                content_digest: "sha256:resource-live",
                created_at: "2026-07-19T02:30:00Z",
                gates: [
                  {
                    created_at: "2026-07-19T02:31:00Z",
                    findings: [],
                    gate: "COMPLIANCE",
                    passed: true,
                    reviewer: "policy-live",
                    version: 1,
                  },
                ],
                job_id: "00000000-0000-0000-0000-000000000501",
                resource_id: "00000000-0000-0000-0000-000000000502",
                resource_type: "MICRO_LECTURE",
                status: "PUBLISHED",
                student_id: "00000000-0000-0000-0000-000000000401",
                version: 2,
              },
            ],
            page: { number: 1, size: 20, total_items: 1, total_pages: 1 },
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.url.endsWith("/api/v1/admin/agent-runs/RUN-LIVE-501")) {
        return new Response(
          JSON.stringify({
            checkpoint_thread_id: "thread-live",
            completed_at: "2026-07-19T02:32:00Z",
            created_at: "2026-07-19T02:30:00Z",
            error_code: null,
            event_id: "event-live-501",
            external_run_id: "RUN-LIVE-501",
            fallback_used: false,
            input_snapshot: { redacted: true },
            latest_checkpoint_id: "checkpoint-live",
            latest_sequence: 7,
            output_snapshot: { redacted: true },
            route: "orchestrator-live",
            started_at: "2026-07-19T02:30:01Z",
            status: "SUCCEEDED",
            student_id: "00000000-0000-0000-0000-000000000401",
            tool_calls: [
              {
                argument_digest: "sha256:args-live",
                error_code: null,
                event_type: "TOOL_SUCCEEDED",
                latency_ms: 83,
                node: "orchestrator-live",
                occurred_at: "2026-07-19T02:30:02Z",
                result_digest: "sha256:result-live",
                retry_count: 0,
                sequence: 4,
                status: "SUCCEEDED",
                tool_name: "evidence.live.read",
              },
            ],
            trace_id: "trace-live-501",
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      throw new Error(`Unexpected request: ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const resources = renderAdmin("/admin/resources");
    expect(await screen.findByText("MICRO_LECTURE")).toBeVisible();
    expect(screen.getByRole("table", { name: "待审核资源" })).toHaveTextContent("policy-live");
    resources.unmount();

    renderAdmin("/admin/agent-runs?run_id=RUN-LIVE-501");
    expect((await screen.findAllByText("evidence.live.read"))[0]).toBeVisible();
    expect(screen.getByRole("heading", { name: "执行时间线 · RUN-LIVE-501" })).toBeVisible();
    expect(screen.queryByText("raw prompt must never render")).not.toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [request] of fetchMock.mock.calls) {
      expect((request as Request).headers.get("Authorization")).toBe("Bearer admin-access");
    }
  });

  it("submits confirmed idempotent backup and restore commands to the API", async () => {
    saveServerUrl("https://api.example.test");
    const backupId = "00000000-0000-0000-0000-000000000601";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            active_connections: 4,
            connected: true,
            database_size_bytes: 4096,
            engine: "PostgreSQL",
            last_backup: null,
            schema_revision: "0011",
            slow_query_count: 0,
            table_count: 31,
            tables: [],
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            content_digest: "sha256:backup-live",
            created_at: "2026-07-19T02:30:00Z",
            id: backupId,
            size_bytes: 8192,
            status: "AVAILABLE",
          }),
          { headers: { "Content-Type": "application/json" }, status: 201 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            backup_id: backupId,
            completed_at: "2026-07-19T02:32:00Z",
            error_code: null,
            id: "00000000-0000-0000-0000-000000000602",
            operation: "DATABASE_RESTORE",
            requested_at: "2026-07-19T02:31:00Z",
            status: "SUCCEEDED",
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/database");

    await screen.findByText("0011");
    await user.click(screen.getByRole("button", { name: "创建数据库备份" }));
    await user.type(screen.getByRole("textbox", { name: "输入确认短语" }), "BACKUP DATABASE");
    await user.click(screen.getByRole("button", { name: "确认备份" }));
    expect(await screen.findByRole("status", { name: "数据库操作状态" })).toHaveTextContent(
      "备份已创建",
    );

    await user.click(screen.getByRole("button", { name: "恢复备份" }));
    await user.type(screen.getByRole("textbox", { name: "输入确认短语" }), "RESTORE DATABASE");
    await user.click(screen.getByRole("button", { name: "确认恢复" }));
    expect(screen.getByRole("status", { name: "数据库操作状态" })).toHaveTextContent("恢复已完成");

    const backupRequest = fetchMock.mock.calls[1]?.[0] as Request;
    const restoreRequest = fetchMock.mock.calls[2]?.[0] as Request;
    expect(backupRequest.url).toBe("https://api.example.test/api/v1/admin/system/db/backup");
    expect(backupRequest.headers.get("Idempotency-Key")).toMatch(/^database-backup-/);
    await expect(backupRequest.clone().json()).resolves.toEqual({
      confirmation: "BACKUP DATABASE",
    });
    expect(restoreRequest.url).toBe("https://api.example.test/api/v1/admin/system/db/restore");
    expect(restoreRequest.headers.get("Idempotency-Key")).toMatch(/^database-restore-/);
    await expect(restoreRequest.clone().json()).resolves.toEqual({
      backup_id: backupId,
      confirmation: "RESTORE DATABASE",
    });
  });

  it("loads health, metrics, logs, and database status from protected APIs", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.url.endsWith("/api/v1/admin/system/health")) {
        return new Response(
          JSON.stringify({
            checked_at: "2026-07-19T02:30:00Z",
            components: [
              {
                component: "Live Sandbox",
                detail: "queue depth 17",
                latency_ms: 73,
                status: "DEGRADED",
              },
            ],
            status: "DEGRADED",
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.url.includes("/api/v1/admin/system/metrics")) {
        return new Response(
          JSON.stringify({
            items: [
              {
                average_latency_ms: 120,
                calls: 41,
                error_rate: 0.05,
                errors: 2,
                model: "live-model",
                p95_latency_ms: 240,
                provider_type: "LLM",
                rate_limited: 1,
                vendor: "Live Metrics Vendor",
              },
            ],
            since: "2026-07-18T02:30:00Z",
            until: "2026-07-19T02:30:00Z",
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.url.includes("/api/v1/admin/system/logs")) {
        return new Response(
          JSON.stringify({
            items: [
              {
                context: { operation: "live-gate" },
                created_at: "2026-07-19T02:30:00Z",
                id: "00000000-0000-0000-0000-000000000301",
                level: "ERROR",
                message: "live.acceptance.error",
                source: "ERROR",
                trace_id: "trace-live",
              },
            ],
            page: { number: 1, size: 50, total_items: 1, total_pages: 1 },
            truncated: false,
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.url.endsWith("/api/v1/admin/system/db")) {
        return new Response(
          JSON.stringify({
            active_connections: 4,
            connected: true,
            database_size_bytes: 4096,
            engine: "PostgreSQL LIVE",
            last_backup: null,
            schema_revision: "0011-live",
            slow_query_count: 0,
            table_count: 31,
            tables: [],
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      throw new Error(`Unexpected request: ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const health = renderAdmin("/admin/health");
    expect(await screen.findByText("Live Sandbox")).toBeVisible();
    health.unmount();

    const metrics = renderAdmin("/admin/metrics");
    expect((await screen.findAllByText("Live Metrics Vendor"))[0]).toBeVisible();
    metrics.unmount();

    const logs = renderAdmin("/admin/logs");
    expect(await screen.findByText("live.acceptance.error")).toBeVisible();
    logs.unmount();

    renderAdmin("/admin/database");
    expect(await screen.findByText("0011-live")).toBeVisible();

    expect(fetchMock).toHaveBeenCalledTimes(4);
    for (const [request] of fetchMock.mock.calls) {
      expect((request as Request).headers.get("Authorization")).toBe("Bearer admin-access");
    }
  });

  it("loads immutable audit records from the protected audit projection", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [
            {
              context: { backup_id: "backup-live-701" },
              created_at: "2026-07-19T02:30:00Z",
              id: "00000000-0000-0000-0000-000000000701",
              level: "INFO",
              message: "DATABASE_BACKUP_CREATED",
              source: "AUDIT",
              trace_id: "trace-audit-live-701",
            },
          ],
          page: { number: 1, size: 50, total_items: 1, total_pages: 1 },
          truncated: false,
        }),
        { headers: { "Content-Type": "application/json" }, status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderAdmin("/admin/audit");

    expect(await screen.findByText("DATABASE_BACKUP_CREATED")).toBeVisible();
    expect(screen.getByText("trace-audit-live-701")).toBeVisible();
    expect(screen.getByText(/backup-live-701/)).toBeVisible();
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.url).toContain("/api/v1/admin/system/logs");
    expect(request.url).toContain("source=AUDIT");
    expect(request.headers.get("Authorization")).toBe("Bearer admin-access");
  });

  it("loads provider configuration from the generated API instead of renderer fixtures", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [
            {
              api_key_masked: "••••LIVE",
              created_at: "2026-07-19T02:30:00Z",
              enabled: true,
              endpoint: "https://provider.example.test/v1",
              id: "00000000-0000-0000-0000-000000000201",
              model: "live-model",
              params: {},
              provider_type: "LLM",
              updated_at: "2026-07-19T02:30:00Z",
              vendor: "Live Provider",
              version: 1,
            },
          ],
        }),
        { headers: { "Content-Type": "application/json" }, status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderAdmin("/admin/providers");

    expect(await screen.findByText("Live Provider")).toBeVisible();
    expect(screen.getByRole("table", { name: "Provider 配置" })).toHaveTextContent("••••LIVE");
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.url).toBe("https://api.example.test/api/v1/admin/providers");
    expect(request.headers.get("Authorization")).toBe("Bearer admin-access");
  });

  it("masks provider secrets and tests connectivity without revealing keys", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            items: [
              {
                api_key_masked: "••••••••7H2K",
                created_at: "2026-07-19T02:30:00Z",
                enabled: true,
                endpoint: "https://provider.example.test/v1",
                id: "00000000-0000-0000-0000-000000000202",
                model: "spark-compatible",
                params: {},
                provider_type: "LLM",
                updated_at: "2026-07-19T02:30:00Z",
                vendor: "讯飞 LLM",
                version: 1,
              },
            ],
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ detail: "ok", latency_ms: 428, ok: true, status_code: 200 }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/providers");

    expect(await screen.findByText("讯飞 LLM")).toBeVisible();
    expect(screen.getByRole("table", { name: "Provider 配置" })).toHaveTextContent("••••••••7H2K");
    expect(screen.queryByText("PLAINTEXT_KEY_SHOULD_NOT_RENDER")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "测试讯飞 LLM 连通性" }));
    expect(screen.getByRole("status", { name: "Provider 测试状态" })).toHaveTextContent("连接成功");
  });
});

describe("admin overview aggregate metrics (FE-013)", () => {
  it("renders BE-017 overview counts instead of the hardcoded 248 / 7 values", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.url.endsWith("/api/v1/admin/overview")) {
        return new Response(
          JSON.stringify({
            active_students: 312,
            pending_registrations: 4,
            resource_reviews: 9,
            due_reviews: 18,
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.url.includes("/api/v1/admin/registrations/pending")) {
        return new Response(JSON.stringify([]), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      throw new Error(`Unexpected request: ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAdmin("/admin/overview");

    const metrics = await screen.findByRole("region", { name: "平台概览指标" });
    expect(await within(metrics).findByText("312")).toBeVisible();
    expect(within(metrics).getByText("9")).toBeVisible();
    expect(within(metrics).getByText("4")).toBeVisible();
    // Hardcoded placeholder values must not leak through.
    expect(metrics).not.toHaveTextContent("248");
    expect(metrics).not.toHaveTextContent("+12 本周");
    expect(metrics).not.toHaveTextContent("2 项高优先级");

    const overviewRequest = fetchMock.mock.calls.find(([request]) =>
      (request as Request).url.endsWith("/api/v1/admin/overview"),
    )?.[0] as Request;
    expect(overviewRequest.headers.get("Authorization")).toBe("Bearer admin-access");
  });

  it("falls back to an error state with retry when the overview endpoint fails", async () => {
    saveServerUrl("https://api.example.test");
    let overviewFailing = true;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.url.endsWith("/api/v1/admin/overview")) {
        if (overviewFailing) {
          return new Response(JSON.stringify({ detail: "租户概览不可用" }), {
            headers: { "Content-Type": "application/json" },
            status: 503,
          });
        }
        return new Response(
          JSON.stringify({
            active_students: 27,
            pending_registrations: 1,
            resource_reviews: 2,
            due_reviews: 3,
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.url.includes("/api/v1/admin/registrations/pending")) {
        return new Response(JSON.stringify([]), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      throw new Error(`Unexpected request: ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/overview");

    const alert = await screen.findByRole("alert", { name: "管理概览错误" });
    expect(alert).toHaveTextContent("租户概览不可用");

    // Next overview fetch succeeds so the manual retry recovers the metrics.
    overviewFailing = false;
    await user.click(screen.getByRole("button", { name: "重试概览" }));
    const metrics = screen.getByRole("region", { name: "平台概览指标" });
    expect(await within(metrics).findByText("27")).toBeVisible();
  });
});
