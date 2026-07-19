import {
  CaretDown,
  Gauge,
  GraduationCap,
  ListMagnifyingGlass,
  MagnifyingGlass,
  Pulse,
  ShieldCheck,
  SignOut,
  Sparkle,
  UserCircle,
  Users,
} from "@phosphor-icons/react";
import {
  adminAgentRunApiV1AdminAgentRunsExternalRunIdGet,
  client,
  type AdminAgentRunView,
  type AdminSystemHealthView,
} from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";
import { AppShell, StatePanel } from "@pymentor/ui";
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";

import { AdminLoginPage } from "./features/auth/admin-login";
import {
  AdminAuthProvider,
  type AdminAuthApi,
  type AuthSession,
  useAdminAuth,
} from "./features/auth/auth-session";
import {
  AuditPage,
  DatabasePage,
  HealthPage,
  LogsPage,
  MetricsPage,
  OverviewPage,
  ProvidersPage,
  ResourceReviewPage,
  StudentDetailPage,
  StudentsPage,
} from "./features/operations/admin-operation-pages";
import { ADMIN_APP_VERSION, SettingsPage } from "./features/operations/admin-settings-page";

const navigation = [
  { href: "/admin/overview", label: "概览", icon: <Gauge size={21} /> },
  { href: "/admin/students", label: "用户与课程", icon: <Users size={21} /> },
  {
    href: "/admin/resources",
    label: "资源审核",
    icon: <GraduationCap size={21} />,
  },
  {
    href: "/admin/agent-runs",
    label: "Agent 调用回放",
    icon: <Sparkle size={21} />,
  },
  { href: "/admin/audit", label: "系统审计", icon: <ShieldCheck size={21} /> },
  { href: "/admin/health", label: "运行监控", icon: <Pulse size={21} /> },
] as const;

function AdminHeader() {
  const { session, signOut } = useAdminAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function handlePointer(event: MouseEvent) {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handlePointer);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handlePointer);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  function handleSignOut() {
    setOpen(false);
    signOut();
    navigate("/login", { replace: true });
  }

  const label = session?.displayName ?? "系统管理员";

  return (
    <div className="admin-topbar">
      <strong>灵蟒智学 PyMentor Lab · 管理端</strong>
      <label className="admin-global-search">
        <span className="sr-only">搜索管理端内容</span>
        <MagnifyingGlass size={17} />
        <input placeholder="搜索 run_id / 学生 / 任务" type="search" />
      </label>
      <div className="admin-profile-menu" ref={wrapperRef}>
        <button
          aria-expanded={open}
          aria-haspopup="menu"
          className="admin-profile"
          onClick={() => setOpen((current) => !current)}
          type="button"
        >
          <UserCircle size={18} />
          <span>{label}</span>
          <CaretDown size={14} />
        </button>
        {open ? (
          <ul aria-label="管理员会话" className="admin-profile-menu__list" role="menu">
            <li className="admin-profile-menu__session" role="menuiteminfo">
              <UserCircle size={20} />
              <div>
                <strong>{label}</strong>
                <small>
                  {session?.role ? `${session.role} · ` : ""}v{ADMIN_APP_VERSION}
                </small>
              </div>
            </li>
            <li role="none">
              <button onClick={handleSignOut} role="menuitem" type="button">
                <SignOut size={16} /> 退出登录
              </button>
            </li>
          </ul>
        ) : null}
      </div>
    </div>
  );
}

function AgentRunsPage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedRunId = searchParams.get("run_id")?.trim() ?? "";
  const [query, setQuery] = useState(requestedRunId);
  const [run, setRun] = useState<AdminAgentRunView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setRun(null);
    setError(null);
    setQuery(requestedRunId);
    if (!requestedRunId) {
      return () => {
        active = false;
      };
    }
    if (!accessToken) {
      setError("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    client.setConfig({ baseUrl: readServerUrl(), credentials: "include", fetch });
    void adminAgentRunApiV1AdminAgentRunsExternalRunIdGet({
      headers: { Authorization: `Bearer ${accessToken}` },
      path: { external_run_id: requestedRunId },
    })
      .then((result) => {
        if (!active) return;
        if (!result.data) throw new Error("Agent 回放不存在或当前租户无权访问");
        setRun(result.data);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "Agent 回放加载失败");
      });
    return () => {
      active = false;
    };
  }, [accessToken, requestedRunId]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const runId = query.trim();
    setSearchParams(runId ? { run_id: runId } : {});
  }

  return (
    <div className="admin-page">
      <div className="admin-page__heading">
        <div>
          <p className="eyebrow">AGENT OPERATIONS</p>
          <h1>Agent 调用回放</h1>
          <p>查看六类 Agent 的输入、工具调用、结构化输出与最终规则决策</p>
        </div>
        <form onSubmit={submit}>
          <label>
            <span className="sr-only">Agent run ID</span>
            <input
              aria-label="Agent run ID"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="输入 run_id"
              value={query}
            />
          </label>
          <button className="admin-filter-button" type="submit">
            <ListMagnifyingGlass size={18} /> 加载回放
          </button>
        </form>
      </div>

      {!requestedRunId ? <p role="status">输入 run_id 以读取受租户隔离的审计回放。</p> : null}
      {requestedRunId && !run && !error ? <p role="status">正在加载 Agent 回放…</p> : null}
      {error ? <p role="alert">{error}</p> : null}

      <section aria-label="调用指标" className="metric-grid">
        {[
          ["状态", run?.status ?? "-", "持久化审计"],
          ["最新序号", String(run?.latest_sequence ?? 0), "单调事件序列"],
          ["工具调用", String(run?.tool_calls.length ?? 0), "只显示摘要"],
          ["降级", run?.fallback_used ? "YES" : "NO", run?.error_code ?? "无错误码"],
        ].map(([label, value, trend]) => (
          <article className="metric-card" key={label}>
            <p>{label}</p>
            <div>
              <strong>{value}</strong>
              <span>{trend}</span>
            </div>
          </article>
        ))}
      </section>

      <div className="replay-grid">
        <section className="admin-panel call-list" aria-labelledby="call-list-title">
          <h2 id="call-list-title">调用记录</h2>
          <div className="call-list__items">
            {run ? (
              <button className="call-row is-selected" type="button">
                <span>
                  <strong>{run.external_run_id}</strong>
                  <small>{run.route ?? "未记录 route"}</small>
                </span>
                <span>
                  <strong>{run.student_id}</strong>
                  <small>{run.trace_id}</small>
                </span>
                <span className={`call-status call-status--${run.status}`}>{run.status}</span>
              </button>
            ) : null}
          </div>
        </section>

        <section className="admin-panel replay-timeline" aria-labelledby="timeline-title">
          <h2 id="timeline-title">
            执行时间线 · {(run?.external_run_id ?? requestedRunId) || "-"}
          </h2>
          <ol>
            {(run?.tool_calls ?? []).map((tool, index, tools) => (
              <li
                className={index === tools.length - 1 ? "is-current" : ""}
                key={`${tool.sequence}-${tool.tool_name}`}
              >
                <time>{new Date(tool.occurred_at).toLocaleTimeString("zh-CN")}</time>
                <span>
                  <strong>{tool.tool_name}</strong>
                  <small>
                    {tool.event_type} · {tool.status ?? "UNKNOWN"} · {tool.latency_ms}ms · retry{" "}
                    {tool.retry_count}
                  </small>
                </span>
              </li>
            ))}
          </ol>
          <p className="panel-note">
            调用链可回放 · 所有输入输出均按 Schema 保存 · 正式状态由规则组件写入
          </p>
        </section>

        <section className="admin-panel run-detail" aria-labelledby="detail-title">
          <h2 id="detail-title">本次调用详情</h2>
          <dl>
            <div>
              <dt>Route</dt>
              <dd>{run?.route ?? "-"}</dd>
            </div>
            <div>
              <dt>Thread</dt>
              <dd>{run?.checkpoint_thread_id ?? "-"}</dd>
            </div>
            <div>
              <dt>Checkpoint</dt>
              <dd>{run?.latest_checkpoint_id ?? "-"}</dd>
            </div>
            <div>
              <dt>Event</dt>
              <dd>{run?.event_id ?? "-"}</dd>
            </div>
            <div>
              <dt>工具调用</dt>
              <dd>{run?.tool_calls.map((tool) => tool.tool_name).join(" · ") || "-"}</dd>
            </div>
            <div>
              <dt>结果</dt>
              <dd>{run?.status ?? "-"}</dd>
            </div>
            <div>
              <dt>审计</dt>
              <dd>{run ? `trace ${run.trace_id} · 已脱敏` : "-"}</dd>
            </div>
          </dl>
          <div className="constraint-note">
            <strong>关键约束</strong>
            <p>Agent 只能提出建议，不能直接写画像或掌握状态。</p>
          </div>
        </section>
      </div>
    </div>
  );
}

export function describeAdminSystemHealth(systemHealth: AdminSystemHealthView | null) {
  const degradedCount =
    systemHealth?.components?.filter((component) => component.status !== "HEALTHY").length ?? 0;
  if (systemHealth?.status === "DEGRADED" || degradedCount > 0) {
    return { label: "系统存在降级", detail: `${degradedCount} 个组件需要关注` };
  }
  if (systemHealth) {
    return { label: "系统状态正常", detail: "全部服务可用" };
  }
  return { label: "正在检查系统状态", detail: "读取实时健康接口" };
}

function AdminLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const [systemHealth, setSystemHealth] = useState<AdminSystemHealthView | null>(null);
  const operationalPaths = ["/admin/providers", "/admin/metrics", "/admin/logs", "/admin/database"];
  const activeHref = operationalPaths.some((path) => location.pathname.startsWith(path))
    ? "/admin/health"
    : (navigation.find((item) => location.pathname.startsWith(item.href))?.href ??
      "/admin/overview");

  const sidebarStatus = describeAdminSystemHealth(systemHealth);

  return (
    <AppShell
      activeHref={activeHref}
      brand="灵蟒智学"
      header={<AdminHeader />}
      navigation={navigation}
      onNavigate={navigate}
      onToolAction={(tool) =>
        navigate(tool === "settings" ? "/admin/settings" : "/admin/health")
      }
      status={sidebarStatus}
      subtitle="PyMentor Lab · 管理端"
      variant="admin"
    >
      <Routes>
        <Route path="/admin/agent-runs" element={<AgentRunsPage />} />
        <Route path="/admin/health" element={<HealthPage onHealthChange={setSystemHealth} />} />
        <Route path="/admin/metrics" element={<MetricsPage />} />
        <Route path="/admin/providers" element={<ProvidersPage />} />
        <Route path="/admin/logs" element={<LogsPage />} />
        <Route path="/admin/database" element={<DatabasePage />} />
        <Route path="/admin/settings" element={<SettingsPage />} />
        <Route path="/admin/overview" element={<OverviewPage />} />
        <Route path="/admin/students/:studentId" element={<StudentDetailPage />} />
        <Route path="/admin/students" element={<StudentsPage />} />
        <Route path="/admin/resources/*" element={<ResourceReviewPage />} />
        <Route path="/admin/audit/*" element={<AuditPage />} />
        <Route
          path="*"
          element={
            <StatePanel
              description="页面不存在或当前角色无权访问"
              state="error"
              title="找不到管理页面"
            />
          }
        />
      </Routes>
    </AppShell>
  );
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { session, status } = useAdminAuth();

  if (status === "checking") {
    return <StatePanel description="正在验证管理员会话" state="loading" title="检查管理权限" />;
  }
  if (!session || status !== "authenticated") return <Navigate replace to="/login" />;
  if (session.role !== "admin") {
    return (
      <StatePanel
        description="当前学生账号没有管理员权限，请使用授权管理员账号登录"
        state="error"
        title="无权访问管理端"
      />
    );
  }
  return children;
}

function AdminRouteTree() {
  return (
    <Routes>
      <Route path="/login" element={<AdminLoginPage />} />
      <Route path="/" element={<Navigate replace to="/admin/overview" />} />
      <Route path="/admin" element={<Navigate replace to="/admin/overview" />} />
      <Route
        path="*"
        element={
          <RequireAdmin>
            <AdminLayout />
          </RequireAdmin>
        }
      />
    </Routes>
  );
}

export function AdminRoutes({
  api,
  initialSession,
}: {
  api?: AdminAuthApi;
  initialSession?: AuthSession | null;
}) {
  return (
    <AdminAuthProvider api={api} initialSession={initialSession}>
      <AdminRouteTree />
    </AdminAuthProvider>
  );
}
