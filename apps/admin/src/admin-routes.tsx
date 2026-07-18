import {
  CaretDown,
  Gauge,
  GraduationCap,
  ListMagnifyingGlass,
  MagnifyingGlass,
  Pulse,
  ShieldCheck,
  Sparkle,
  Users,
} from "@phosphor-icons/react";
import { AppShell, StatePanel } from "@pymentor/ui";
import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

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

const calls = [
  ["RUN-8F21", "教学主任", "函数边界补救路径", "成功", "4.8s"],
  ["RUN-8F20", "路径规划", "生成今日学习路径", "成功", "3.9s"],
  ["RUN-8F19", "教学资源", "五类资源需求单", "进行中", "12.6s"],
  ["RUN-8F18", "编程教练", "解释 IndexError", "成功", "2.1s"],
  ["RUN-8F17", "测评反馈", "开放题量表评分", "降级", "7.3s"],
] as const;

const timeline = [
  ["23:59:18", "输入校验", "InteractionAccepted"],
  ["23:59:19", "教学主任 Agent", "识别意图：循环边界错误"],
  ["23:59:20", "工具调用", "读取画像与最近证据"],
  ["23:59:21", "路径规划 Agent", "提出补救路径建议"],
  ["23:59:22", "路径验证器", "自动插入前置节点"],
  ["23:59:24", "Outbox", "发布 TASK_COMPILED"],
] as const;

function AdminHeader() {
  return (
    <div className="admin-topbar">
      <strong>灵蟒智学 PyMentor Lab · 管理端</strong>
      <label className="admin-global-search">
        <span className="sr-only">搜索管理端内容</span>
        <MagnifyingGlass size={17} />
        <input placeholder="搜索 run_id / 学生 / 任务" type="search" />
      </label>
      <button className="admin-profile" type="button">
        <span>系统管理员</span>
        <CaretDown size={14} />
      </button>
    </div>
  );
}

function AgentRunsPage() {
  return (
    <div className="admin-page">
      <div className="admin-page__heading">
        <div>
          <p className="eyebrow">AGENT OPERATIONS</p>
          <h1>Agent 调用回放</h1>
          <p>查看六类 Agent 的输入、工具调用、结构化输出与最终规则决策</p>
        </div>
        <button className="admin-filter-button" type="button">
          <ListMagnifyingGlass size={18} /> 筛选调用
        </button>
      </div>

      <section aria-label="调用指标" className="metric-grid">
        {[
          ["今日调用", "1,284", "↑ 8.6%"],
          ["Schema 通过率", "99.4%", "稳定"],
          ["平均耗时", "4.2s", "P95 8.1s"],
          ["降级次数", "17", "1.3%"],
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
        <section
          className="admin-panel call-list"
          aria-labelledby="call-list-title"
        >
          <h2 id="call-list-title">调用记录</h2>
          <div className="call-list__items">
            {calls.map(([id, agent, summary, status, duration], index) => (
              <button
                className={index === 0 ? "call-row is-selected" : "call-row"}
                key={id}
                type="button"
              >
                <span>
                  <strong>{id}</strong>
                  <small>{summary}</small>
                </span>
                <span>
                  <strong>{agent}</strong>
                  <small>{duration}</small>
                </span>
                <span className={`call-status call-status--${status}`}>
                  {status}
                </span>
              </button>
            ))}
          </div>
        </section>

        <section
          className="admin-panel replay-timeline"
          aria-labelledby="timeline-title"
        >
          <h2 id="timeline-title">执行时间线 · RUN-8F21</h2>
          <ol>
            {timeline.map(([time, title, detail], index) => (
              <li
                className={index === timeline.length - 1 ? "is-current" : ""}
                key={time}
              >
                <time>{time}</time>
                <span>
                  <strong>{title}</strong>
                  <small>{detail}</small>
                </span>
              </li>
            ))}
          </ol>
          <p className="panel-note">
            调用链可回放 · 所有输入输出均按 Schema 保存 · 正式状态由规则组件写入
          </p>
        </section>

        <section
          className="admin-panel run-detail"
          aria-labelledby="detail-title"
        >
          <h2 id="detail-title">本次调用详情</h2>
          <dl>
            <div>
              <dt>Agent</dt>
              <dd>教学主任 Orchestrator</dd>
            </div>
            <div>
              <dt>模型 / Provider</dt>
              <dd>讯飞 LLM · temperature 0.2</dd>
            </div>
            <div>
              <dt>输入 Schema</dt>
              <dd>orchestrator_input_v3</dd>
            </div>
            <div>
              <dt>输出 Schema</dt>
              <dd>workflow_decision_v2</dd>
            </div>
            <div>
              <dt>工具调用</dt>
              <dd>profile.read · evidence.query</dd>
            </div>
            <div>
              <dt>结果</dt>
              <dd>PATH_REPLAN_REQUESTED</dd>
            </div>
            <div>
              <dt>审计</dt>
              <dd>已记录 · 可追溯</dd>
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

function AdminLayout() {
  const location = useLocation();
  const operationalPaths = [
    "/admin/providers",
    "/admin/metrics",
    "/admin/logs",
    "/admin/database",
  ];
  const activeHref = operationalPaths.some((path) =>
    location.pathname.startsWith(path),
  )
    ? "/admin/health"
    : (navigation.find((item) => location.pathname.startsWith(item.href))
        ?.href ?? "/admin/overview");

  return (
    <AppShell
      activeHref={activeHref}
      brand="灵蟒智学"
      header={<AdminHeader />}
      navigation={navigation}
      subtitle="PyMentor Lab · 管理端"
      variant="admin"
    >
      <Routes>
        <Route path="/admin/agent-runs" element={<AgentRunsPage />} />
        <Route path="/admin/health" element={<HealthPage />} />
        <Route path="/admin/metrics" element={<MetricsPage />} />
        <Route path="/admin/providers" element={<ProvidersPage />} />
        <Route path="/admin/logs" element={<LogsPage />} />
        <Route path="/admin/database" element={<DatabasePage />} />
        <Route path="/admin/overview" element={<OverviewPage />} />
        <Route
          path="/admin/students/:studentId"
          element={<StudentDetailPage />}
        />
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
    return (
      <StatePanel
        description="正在验证管理员会话"
        state="loading"
        title="检查管理权限"
      />
    );
  }
  if (!session || status !== "authenticated")
    return <Navigate replace to="/login" />;
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
      <Route
        path="/admin"
        element={<Navigate replace to="/admin/overview" />}
      />
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
