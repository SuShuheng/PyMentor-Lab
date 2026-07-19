import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle,
  Database,
  DownloadSimple,
  Eye,
  EyeSlash,
  Funnel,
  Gauge,
  HardDrives,
  LinkSimple,
  MagnifyingGlass,
  PencilSimple,
  Plus,
  Power,
  ShieldCheck,
  Student,
  Trash,
  WarningCircle,
  X,
  Lightning,
} from "@phosphor-icons/react";
import {
  AgentTimelineChart,
  ApiUsageChart,
  ChartFrame,
  MasteryDistributionChart,
  downloadCsv,
} from "@pymentor/charts";
import {
  adminProviderMetricsApiV1AdminSystemMetricsGet,
  adminResourceReviewsApiV1AdminResourcesReviewsGet,
  adminStudentEvidenceApiV1AdminStudentsStudentIdEvidenceGet,
  adminStudentProfileApiV1AdminStudentsStudentIdProfileGet,
  adminStudentProgressApiV1AdminStudentsStudentIdProgressGet,
  adminStudentsApiV1AdminStudentsGet,
  adminSystemHealthApiV1AdminSystemHealthGet,
  adminSystemLogsApiV1AdminSystemLogsGet,
  approveRegistrationApiV1AdminRegistrationsUserIdApprovePost,
  client,
  createDatabaseBackupApiV1AdminSystemDbBackupPost,
  databaseStatusApiV1AdminSystemDbGet,
  type AdminLogPage,
  type AdminResourceReviewPage,
  type AdminEvidencePage,
  type AdminStudentPage,
  type AdminStudentProfile,
  type AdminStudentProgress,
  type AdminSystemHealthView,
  type DatabaseStatusView,
  listPendingApiV1AdminRegistrationsPendingGet,
  type ProviderMetricsView,
  rejectRegistrationApiV1AdminRegistrationsUserIdRejectPost,
  restoreDatabaseBackupApiV1AdminSystemDbRestorePost,
  type PendingRegistration,
  type ProviderConfigView,
  type ProviderType,
} from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";
import { StatePanel } from "@pymentor/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";

import { useAdminAuth } from "../auth/auth-session";
import { fetchAdminOverview } from "./admin-overview-api";
import {
  type ProviderConnectivityResult,
  configureAdminProviderClient,
  createProvider,
  deleteProvider,
  disableProvider,
  enableProvider,
  fetchProviders,
  providerApiError,
  testProviderConnectivity,
  updateProvider,
} from "./admin-provider-api";
import {
  type ProviderPreset,
  findPresetsForVendor,
  pickPresetForVendor,
} from "./admin-provider-presets";
import {
  RESOURCE_TYPES,
  fetchAdminMetrics,
  type AdminMetrics,
  type ResourceStatItem,
} from "./admin-metrics-api";

function AdminPageHeading({
  action,
  description,
  eyebrow = "ADMIN OPERATIONS",
  title,
}: {
  action?: React.ReactNode;
  description: string;
  eyebrow?: string;
  title: string;
}) {
  return (
    <div className="admin-page__heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

const operationLinks = [
  ["/admin/health", "服务健康"],
  ["/admin/metrics", "API 指标"],
  ["/admin/providers", "Provider"],
  ["/admin/logs", "系统日志"],
  ["/admin/database", "数据运维"],
] as const;

function OperationsNav() {
  const location = useLocation();
  return (
    <nav aria-label="运行与数据管理" className="admin-subnav">
      {operationLinks.map(([href, label]) => (
        <Link aria-current={location.pathname === href ? "page" : undefined} key={href} to={href}>
          {label}
        </Link>
      ))}
    </nav>
  );
}

function configureOperationsClient(): void {
  client.setConfig({
    baseUrl: readServerUrl(),
    credentials: "include",
    fetch,
  });
}

function operationsError(error: unknown): string {
  if (error && typeof error === "object") {
    const detail = Reflect.get(error, "detail");
    if (typeof detail === "string") return detail;
    const message = Reflect.get(error, "message");
    if (typeof message === "string") return message;
  }
  return "管理服务暂时不可用，请稍后重试";
}

function registrationLabel(registration: PendingRegistration): string {
  return registration.student_no || registration.email;
}

function commandKey(prefix: string): string {
  return `${prefix}-${globalThis.crypto.randomUUID()}`;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function formatDuration(valueMs: number): string {
  if (!Number.isFinite(valueMs) || valueMs <= 0) return "-";
  if (valueMs < 1000) return `${Math.round(valueMs)}ms`;
  const seconds = valueMs / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = seconds / 60;
  return `${minutes.toFixed(1)}m`;
}

function formatPercent(rate: number): string {
  if (!Number.isFinite(rate)) return "-";
  const clamped = Math.max(0, Math.min(1, rate));
  return `${(clamped * 100).toFixed(1)}%`;
}

function resourceStatsCsvRows(items: readonly ResourceStatItem[]) {
  return items.map((item) => [
    item.resource_type,
    item.total,
    item.succeeded,
    item.success_rate.toFixed(3),
    Math.round(item.avg_generation_ms),
  ]);
}

export function OverviewPage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [registrations, setRegistrations] = useState<PendingRegistration[]>([]);
  const [queueState, setQueueState] = useState<"error" | "loading" | "ready">("loading");
  const [queueError, setQueueError] = useState<string | null>(null);
  const [reloadAttempt, setReloadAttempt] = useState(0);
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [reviewStatus, setReviewStatus] = useState<string | null>(null);

  const overviewQuery = useQuery({
    queryKey: ["admin", "overview", accessToken ?? "anonymous"],
    queryFn: () => fetchAdminOverview({ accessToken: accessToken ?? "" }),
    enabled: Boolean(accessToken),
    // Overview counts change slowly; a 60s TTL keeps the work台 responsive
    // without hammering the aggregate endpoint on every navigation. Automatic
    // retries inherit the QueryClient default (1 in production, disabled in
    // tests); the manual "重试概览" button covers interactive recovery.
    staleTime: 60_000,
    gcTime: 5 * 60_000,
  });

  useEffect(() => {
    let active = true;
    setQueueState("loading");
    setQueueError(null);
    if (!accessToken) {
      setQueueState("error");
      setQueueError("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    configureOperationsClient();
    void listPendingApiV1AdminRegistrationsPendingGet({
      headers: { Authorization: `Bearer ${accessToken}` },
      query: { limit: 50, offset: 0 },
    })
      .then((result) => {
        if (!active) return;
        if (!result.data) throw new Error(operationsError(result.error));
        setRegistrations(result.data);
        setQueueState("ready");
      })
      .catch((error: unknown) => {
        if (!active) return;
        setQueueError(error instanceof Error ? error.message : operationsError(error));
        setQueueState("error");
      });
    return () => {
      active = false;
    };
  }, [accessToken, reloadAttempt]);

  async function review(registration: PendingRegistration, decision: "approved" | "rejected") {
    if (!accessToken) return;
    const label = registrationLabel(registration);
    setReviewingId(registration.user_id);
    setReviewStatus(null);
    configureOperationsClient();
    try {
      const headers = {
        Authorization: `Bearer ${accessToken}`,
        "Idempotency-Key": commandKey(`registration-${decision}`),
      };
      const result =
        decision === "approved"
          ? await approveRegistrationApiV1AdminRegistrationsUserIdApprovePost({
              body: {},
              headers,
              path: { user_id: registration.user_id },
            })
          : await rejectRegistrationApiV1AdminRegistrationsUserIdRejectPost({
              body: { reason: "Rejected from the registration review queue" },
              headers,
              path: { user_id: registration.user_id },
            });
      if (!result.response.ok) throw new Error(operationsError(result.error));
      setRegistrations((current) =>
        current.filter((item) => item.user_id !== registration.user_id),
      );
      setReviewStatus(`${label}${decision === "approved" ? "已批准" : "已拒绝"} · 审计记录已保存`);
    } catch (error) {
      setReviewStatus(error instanceof Error ? error.message : operationsError(error));
    } finally {
      setReviewingId(null);
    }
  }

  return (
    <div className="admin-page">
      <AdminPageHeading
        description="关键运营指标、审核队列与系统风险集中在一个工作台"
        eyebrow="CONTROL CENTER · 2026-07-17"
        title="管理概览"
      />
      {reviewStatus ? (
        <p aria-label="注册审核状态" className="admin-inline-status" role="status">
          {reviewStatus}
        </p>
      ) : null}
      <section aria-label="平台概览指标" className="metric-grid">
        {overviewQuery.isLoading || overviewQuery.isPending ? (
          <p aria-label="管理概览加载" className="admin-empty-row" role="status">
            正在加载平台概览指标…
          </p>
        ) : null}
        {overviewQuery.isError ? (
          <div aria-label="管理概览错误" className="admin-empty-row" role="alert">
            <p>
              {overviewQuery.error instanceof Error
                ? overviewQuery.error.message
                : "管理概览数据暂时不可用，请稍后重试"}
            </p>
            <button onClick={() => overviewQuery.refetch()} type="button" aria-label="重试概览">
              重试
            </button>
          </div>
        ) : null}
        {overviewQuery.data
          ? (
              [
                ["活跃学生", String(overviewQuery.data.active_students), "实时"],
                ["待审核注册", String(overviewQuery.data.pending_registrations), "需人工处理"],
                ["资源审校", String(overviewQuery.data.resource_reviews), "实时"],
                ["到期复测", String(overviewQuery.data.due_reviews), "服务端计划"],
              ] as const
            ).map(([label, value, trend]) => (
              <article className="metric-card" key={label}>
                <p>{label}</p>
                <div>
                  <strong>{value}</strong>
                  <span>{trend}</span>
                </div>
              </article>
            ))
          : null}
      </section>
      <div className="overview-grid">
        <section
          aria-label="待审核注册"
          className="admin-panel admin-panel--compact registration-queue"
        >
          <div className="admin-panel__heading">
            <div>
              <p className="eyebrow">REGISTRATION QUEUE</p>
              <h2>待审核注册</h2>
            </div>
            <span>{registrations.length} 项</span>
          </div>
          {queueState === "loading" ? (
            <p aria-label="注册队列状态" role="status">
              正在加载待审核注册…
            </p>
          ) : null}
          {queueState === "error" ? (
            <div aria-label="注册队列错误" role="alert">
              <p>{queueError}</p>
              <button onClick={() => setReloadAttempt((attempt) => attempt + 1)} type="button">
                重试
              </button>
            </div>
          ) : null}
          {queueState === "ready" && registrations.length ? (
            <ul>
              {registrations.map((registration) => (
                <li key={registration.user_id}>
                  <span className="admin-avatar">
                    <Student size={18} />
                  </span>
                  <div>
                    <strong>{registrationLabel(registration)}</strong>
                    <small>
                      {registration.email} ·{" "}
                      {new Date(registration.created_at).toLocaleString("zh-CN")}
                    </small>
                  </div>
                  <div className="admin-row-actions">
                    <button
                      aria-label={`拒绝${registrationLabel(registration)}的注册`}
                      disabled={reviewingId === registration.user_id}
                      onClick={() => void review(registration, "rejected")}
                      type="button"
                    >
                      <X size={15} />
                    </button>
                    <button
                      aria-label={`批准${registrationLabel(registration)}的注册`}
                      className="is-primary"
                      disabled={reviewingId === registration.user_id}
                      onClick={() => void review(registration, "approved")}
                      type="button"
                    >
                      <Check size={15} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          ) : queueState === "ready" ? (
            <p className="admin-empty-row">当前没有待审核注册</p>
          ) : null}
        </section>
        <section
          className="admin-panel admin-panel--compact overview-risk"
          aria-labelledby="risk-title"
        >
          <div className="admin-panel__heading">
            <div>
              <p className="eyebrow">ATTENTION</p>
              <h2 id="risk-title">需要处理</h2>
            </div>
          </div>
          <ul>
            <li>
              <WarningCircle size={18} />
              <div>
                <strong>图像 Provider 已降级 18 分钟</strong>
                <small>文字资源仍正常发布</small>
              </div>
              <Link to="/admin/providers">检查</Link>
            </li>
            <li>
              <ShieldCheck size={18} />
              <div>
                <strong>2 个资源版本等待人工审校</strong>
                <small>包含来源映射与合规报告</small>
              </div>
              <Link to="/admin/resources">审校</Link>
            </li>
            <li>
              <Database size={18} />
              <div>
                <strong>最近备份已完成</strong>
                <small>2026-07-17 03:00 · 已校验</small>
              </div>
              <Link to="/admin/database">查看</Link>
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}

export function StudentsPage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [students, setStudents] = useState<AdminStudentPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setError(null);
    if (!accessToken) {
      setError("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    configureOperationsClient();
    void adminStudentsApiV1AdminStudentsGet({
      headers: { Authorization: `Bearer ${accessToken}` },
      query: { page, page_size: 2, q: query.trim() || undefined },
    })
      .then((result) => {
        if (!active) return;
        if (!result.data) throw new Error(operationsError(result.error));
        setStudents(result.data);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : operationsError(caught));
      });
    return () => {
      active = false;
    };
  }, [accessToken, page, query]);

  const pageCount = students?.page.total_pages ?? 1;

  return (
    <div className="admin-page">
      <AdminPageHeading
        description="按服务端查询条件浏览学生、课程、画像与学习证据"
        title="用户与课程"
      />
      <section className="admin-panel admin-table-panel">
        <div className="admin-table-toolbar">
          <label className="admin-filter-field">
            <MagnifyingGlass size={17} />
            <span className="sr-only">筛选学生</span>
            <input
              aria-label="筛选学生"
              onChange={(event) => {
                setQuery(event.target.value);
                setPage(1);
              }}
              placeholder="按姓名、学号或班级筛选"
              type="search"
              value={query}
            />
          </label>
          <button className="admin-filter-button" type="button">
            <Funnel size={16} /> 状态：全部
          </button>
          <span>
            {query
              ? `筛选结果 ${students?.page.total_items ?? 0} 人`
              : `共 ${students?.page.total_items ?? 0} 人 · 服务端分页`}
          </span>
        </div>
        {!students && !error ? <p role="status">正在加载学生列表…</p> : null}
        {error ? <p role="alert">{error}</p> : null}
        <div className="admin-table-scroll">
          <table aria-label="学生列表" className="admin-data-table">
            <thead>
              <tr>
                <th>学生</th>
                <th>邮箱</th>
                <th>状态</th>
                <th>已完成任务</th>
                <th>到期复测</th>
                <th>
                  <span className="sr-only">操作</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {(students?.items ?? []).map((student) => (
                <tr key={student.id}>
                  <th scope="row">
                    <strong>{student.display_name ?? student.email}</strong>
                    <small>{student.student_no ?? student.id}</small>
                  </th>
                  <td>{student.email}</td>
                  <td>
                    <span className={`admin-badge is-${student.status.toLowerCase()}`}>
                      {student.status}
                    </span>
                  </td>
                  <td>{student.completed_tasks}</td>
                  <td>{student.due_reviews}</td>
                  <td>
                    <Link
                      aria-label={`查看${student.display_name ?? student.email}的学习详情`}
                      to={`/admin/students/${student.id}`}
                    >
                      查看 <ArrowRight size={14} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="admin-pagination">
          <button
            aria-label="上一页"
            disabled={page === 1}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
            type="button"
          >
            <ArrowLeft size={15} />
          </button>
          <span>
            第 {page} / {pageCount} 页
          </span>
          <button
            aria-label="下一页"
            disabled={page === pageCount}
            onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
            type="button"
          >
            <ArrowRight size={15} />
          </button>
        </div>
      </section>
    </div>
  );
}

export function StudentDetailPage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const { studentId } = useParams<{ studentId: string }>();
  const [profile, setProfile] = useState<AdminStudentProfile | null>(null);
  const [progress, setProgress] = useState<AdminStudentProgress | null>(null);
  const [evidence, setEvidence] = useState<AdminEvidencePage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!accessToken || !studentId) {
      setError("学生身份或管理员会话无效");
      return () => {
        active = false;
      };
    }
    configureOperationsClient();
    const headers = { Authorization: `Bearer ${accessToken}` };
    void Promise.all([
      adminStudentProfileApiV1AdminStudentsStudentIdProfileGet({
        headers,
        path: { student_id: studentId },
      }),
      adminStudentProgressApiV1AdminStudentsStudentIdProgressGet({
        headers,
        path: { student_id: studentId },
      }),
      adminStudentEvidenceApiV1AdminStudentsStudentIdEvidenceGet({
        headers,
        path: { student_id: studentId },
        query: { page: 1, page_size: 20 },
      }),
    ])
      .then(([profileResult, progressResult, evidenceResult]) => {
        if (!active) return;
        if (!profileResult.data || !progressResult.data || !evidenceResult.data) {
          throw new Error(
            operationsError(profileResult.error ?? progressResult.error ?? evidenceResult.error),
          );
        }
        setProfile(profileResult.data);
        setProgress(progressResult.data);
        setEvidence(evidenceResult.data);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : operationsError(caught));
      });
    return () => {
      active = false;
    };
  }, [accessToken, studentId]);

  return (
    <div className="admin-page">
      <AdminPageHeading
        action={
          <Link className="admin-filter-button" to="/admin/students">
            <ArrowLeft size={15} /> 返回学生列表
          </Link>
        }
        description={`${studentId ?? "未知学生"} · Profile v${profile?.version ?? "-"}`}
        title="学生学习详情"
      />
      {!profile && !error ? <p role="status">正在加载学生学习详情…</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      <section aria-label="学生概览" className="metric-grid">
        {[
          ["稳定掌握", String(progress?.mastery_counts.STABLE_MASTERY ?? 0), "规则状态"],
          ["初步掌握", String(progress?.mastery_counts.INITIAL_MASTERY ?? 0), "等待复测"],
          ["到期复测", String(progress?.due_reviews ?? 0), "服务端计划"],
          [
            "证据记录",
            String(evidence?.page.total_items ?? 0),
            progress?.current_node_id ?? "无当前节点",
          ],
        ].map(([label, value, note]) => (
          <article className="metric-card" key={label}>
            <p>{label}</p>
            <div>
              <strong>{value}</strong>
              <span>{note}</span>
            </div>
          </article>
        ))}
      </section>
      <div className="student-detail-grid">
        <section aria-label="掌握与复测" className="admin-panel admin-panel--compact">
          <div className="admin-panel__heading">
            <div>
              <p className="eyebrow">MASTERY & REVIEW</p>
              <h2>掌握与复测</h2>
            </div>
          </div>
          <ul className="mastery-review-list">
            {(profile?.dimensions ?? []).map((dimension) => (
              <li key={`${dimension.dimension}-${dimension.scope_key}`}>
                <CheckCircle size={18} weight="fill" />
                <div>
                  <strong>{dimension.dimension}</strong>
                  <small>
                    {dimension.scope_key} · score {dimension.score.toFixed(2)} · confidence{" "}
                    {dimension.confidence.toFixed(2)}
                  </small>
                </div>
              </li>
            ))}
          </ul>
          <p className="admin-authority-note">
            <ShieldCheck size={15} /> 正式掌握状态只允许由规则引擎写入
          </p>
        </section>
        <section className="admin-panel admin-panel--compact admin-table-panel">
          <div className="admin-panel__heading">
            <div>
              <p className="eyebrow">EVIDENCE LEDGER</p>
              <h2>最近学习证据</h2>
            </div>
          </div>
          <table aria-label="学习证据" className="admin-data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>类型</th>
                <th>结论</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {(evidence?.items ?? []).map((item) => (
                <tr key={item.id}>
                  <th scope="row">{item.event_id}</th>
                  <td>{item.event_type}</td>
                  <td>{item.node_id ?? item.task_id ?? "-"}</td>
                  <td>{new Date(item.created_at).toLocaleString("zh-CN")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}

export function ResourceReviewPage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [reviews, setReviews] = useState<AdminResourceReviewPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!accessToken) {
      setError("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    configureOperationsClient();
    void adminResourceReviewsApiV1AdminResourcesReviewsGet({
      headers: { Authorization: `Bearer ${accessToken}` },
      query: { page: 1, page_size: 20 },
    })
      .then((result) => {
        if (!active) return;
        if (!result.data) throw new Error(operationsError(result.error));
        setReviews(result.data);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : operationsError(caught));
      });
    return () => {
      active = false;
    };
  }, [accessToken]);

  return (
    <div className="admin-page">
      <AdminPageHeading
        action={
          <Link className="admin-filter-button" to="/admin/resources/stats">
            <Gauge size={15} /> 资源统计
          </Link>
        }
        description="核对来源映射、事实性、合规性与版本差异后再发布"
        title="资源审核"
      />
      <section className="admin-panel admin-table-panel">
        <div className="admin-table-toolbar">
          <strong>资源审校记录</strong>
          <span>{reviews?.page.total_items ?? 0} 项 · 发布门禁由后端强制执行</span>
        </div>
        {!reviews && !error ? <p role="status">正在加载资源审校记录…</p> : null}
        {error ? <p role="alert">{error}</p> : null}
        <table aria-label="待审核资源" className="admin-data-table">
          <thead>
            <tr>
              <th>资源类型</th>
              <th>版本</th>
              <th>状态</th>
              <th>内容摘要</th>
              <th>门禁证据</th>
            </tr>
          </thead>
          <tbody>
            {(reviews?.items ?? []).map((resource) => (
              <tr key={resource.resource_id}>
                <th scope="row">
                  <strong>{resource.resource_type}</strong>
                  <small>{resource.resource_id}</small>
                </th>
                <td>v{resource.version}</td>
                <td>{resource.status}</td>
                <td>
                  <code>{resource.content_digest}</code>
                </td>
                <td>
                  {resource.gates.map((gate) => (
                    <span
                      className={`admin-badge is-${gate.passed ? "active" : "paused"}`}
                      key={`${gate.gate}-${gate.version}`}
                    >
                      {gate.gate} · {gate.passed ? "PASSED" : "FAILED"} · {gate.reviewer}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="admin-authority-note">
          <ShieldCheck size={15} /> 此页面只读；审校与发布由后端双门禁及审计记录决定。
        </p>
      </section>
    </div>
  );
}

function exportResourceStatsCsv(items: readonly ResourceStatItem[]): void {
  downloadCsv(
    `resource-stats-${new Date().toISOString().slice(0, 10)}.csv`,
    ["resource_type", "total", "succeeded", "success_rate", "avg_generation_ms"],
    resourceStatsCsvRows(items),
  );
}

export function ResourceStatsPage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [courseId, setCourseId] = useState("");
  // Draft filter values; applied on submit so the network request and URL
  // stay in sync with what the user confirms.
  const [draft, setDraft] = useState({ courseId: "", since: "", until: "" });
  const [reloadAttempt, setReloadAttempt] = useState(0);

  const statsQuery = useQuery({
    queryKey: [
      "admin",
      "resource-stats",
      accessToken ?? "anonymous",
      draft.courseId,
      draft.since,
      draft.until,
      reloadAttempt,
    ],
    queryFn: () =>
      fetchAdminMetrics({
        accessToken: accessToken ?? "",
        courseId: draft.courseId,
        since: draft.since,
        until: draft.until,
      }),
    enabled: Boolean(accessToken),
    // Per-type aggregates change slowly; a 60s TTL keeps the panel responsive
    // without re-running the server-side grouping on every navigation.
    staleTime: 60_000,
    gcTime: 5 * 60_000,
  });

  function applyFilters() {
    setDraft({ courseId: courseId.trim(), since, until });
  }

  // FE-026 only consumes the `resource_stats` field of the shared BE-028
  // `GET /api/v1/admin/metrics` payload (reusing FE-025's wrapper); the
  // advanced-chart fields are ignored here so FE-025's pages stay the single
  // owner of those inputs.
  const resourceStats = statsQuery.data?.resource_stats;
  const statsItems = resourceStats?.items ?? [];
  const itemsByType = new Map(statsItems.map((item) => [item.resource_type, item]));
  // Use the largest avg generation time as the relative scale for sparklines
  // so every per-type bar is comparable in one black-white band.
  const maxGenerationMs = Math.max(1, ...(statsItems.map((item) => item.avg_generation_ms) ?? [1]));

  return (
    <div className="admin-page">
      <AdminPageHeading
        action={
          <button
            aria-label="导出 CSV"
            className="admin-filter-button"
            disabled={!statsItems.length}
            onClick={() => exportResourceStatsCsv(statsItems)}
            type="button"
          >
            <DownloadSimple size={16} /> 导出 CSV
          </button>
        }
        description="按资源类型聚合的生成量、成功率与平均生成耗时（来自 BE-028 resource_stats）"
        eyebrow="RESOURCE ANALYTICS · FE-026"
        title="资源统计"
      />
      <section aria-label="资源统计筛选" className="admin-panel admin-panel--compact">
        <form
          className="admin-table-toolbar"
          onSubmit={(event) => {
            event.preventDefault();
            applyFilters();
          }}
        >
          <label className="admin-filter-field">
            <Funnel size={16} />
            <span>起始日期</span>
            <input
              aria-label="起始日期"
              onChange={(event) => setSince(event.target.value)}
              type="date"
              value={since}
            />
          </label>
          <label className="admin-filter-field">
            <Funnel size={16} />
            <span>结束日期</span>
            <input
              aria-label="结束日期"
              onChange={(event) => setUntil(event.target.value)}
              type="date"
              value={until}
            />
          </label>
          <label className="admin-filter-field">
            <Funnel size={16} />
            <span>课程 ID</span>
            <input
              aria-label="课程 ID"
              onChange={(event) => setCourseId(event.target.value)}
              placeholder="可选，留空汇总所有课程"
              type="text"
              value={courseId}
            />
          </label>
          <button className="admin-filter-button" type="submit">
            <Funnel size={15} /> 应用筛选
          </button>
          {draft.courseId || draft.since || draft.until ? (
            <span>
              已筛选：{[draft.since, draft.until].filter(Boolean).join(" ~ ")}
              {draft.courseId ? ` · 课程 ${draft.courseId}` : ""}
            </span>
          ) : (
            <span>当前窗口：全租户汇总</span>
          )}
        </form>
      </section>
      {statsQuery.isLoading || statsQuery.isPending ? (
        <p aria-label="资源统计加载" className="admin-empty-row" role="status">
          正在加载资源统计…
        </p>
      ) : null}
      {statsQuery.isError ? (
        <div aria-label="资源统计错误" className="admin-empty-row" role="alert">
          <p>
            {statsQuery.error instanceof Error
              ? statsQuery.error.message
              : "资源统计数据暂时不可用，请稍后重试"}
          </p>
          <button
            aria-label="重试统计"
            onClick={() => setReloadAttempt((attempt) => attempt + 1)}
            type="button"
          >
            重试
          </button>
        </div>
      ) : null}
      {statsQuery.data ? (
        <section aria-label="资源统计" className="admin-resource-stats">
          <ChartFrame
            columns={["资源类型", "生成量", "成功率", "平均生成耗时"]}
            description="后端聚合的资源生成量、成功率与平均耗时；课程维度由 BE-028 强制隔离"
            rows={RESOURCE_TYPES.map((resourceType) => {
              const item = itemsByType.get(resourceType);
              return [
                resourceType,
                String(item?.total ?? 0),
                formatPercent(item?.success_rate ?? 0),
                formatDuration(item?.avg_generation_ms ?? 0),
              ];
            })}
            title="资源生成统计"
          >
            <ul className="admin-resource-stats__rows">
              {RESOURCE_TYPES.map((resourceType) => {
                const item = itemsByType.get(resourceType);
                const total = item?.total ?? 0;
                const successRate = item?.success_rate ?? 0;
                const generationMs = item?.avg_generation_ms ?? 0;
                return (
                  <li key={resourceType}>
                    <span className="admin-resource-stats__type">{resourceType}</span>
                    <span className="admin-resource-stats__count">
                      <strong>{total}</strong>
                      <small>成功 {item?.succeeded ?? 0}</small>
                    </span>
                    <span className="admin-resource-stats__gauge">
                      <progress
                        aria-label={`${resourceType}成功率`}
                        max={100}
                        value={Math.round(successRate * 100)}
                      />
                      <strong>{formatPercent(successRate)}</strong>
                    </span>
                    <span className="admin-resource-stats__sparkline">
                      <progress
                        aria-label={`${resourceType}平均生成耗时`}
                        max={100}
                        value={Math.round((generationMs / maxGenerationMs) * 100)}
                      />
                      <strong>{formatDuration(generationMs)}</strong>
                    </span>
                  </li>
                );
              })}
            </ul>
          </ChartFrame>
          <p className="admin-authority-note">
            <ShieldCheck size={15} /> 统计为只读聚合；课程范围与租户隔离由 BE-028 强制执行。
          </p>
        </section>
      ) : null}
    </div>
  );
}

const PROVIDER_TYPES: ProviderType[] = [
  "LLM",
  "TTS",
  "ASR",
  "IMAGE",
  "OCR",
  "MODERATION",
  "EMBEDDING",
];

type ProviderFormMode = "create" | "edit";

type ProviderFormState = {
  provider_type: ProviderType;
  vendor: string;
  model: string;
  api_key: string;
  endpoint: string;
  enabled: boolean;
};

const EMPTY_PROVIDER_FORM: ProviderFormState = {
  provider_type: "LLM",
  vendor: "",
  model: "",
  api_key: "",
  endpoint: "",
  enabled: false,
};

function formFromProvider(provider: ProviderConfigView): ProviderFormState {
  return {
    provider_type: provider.provider_type,
    vendor: provider.vendor,
    model: provider.model,
    api_key: "",
    endpoint: provider.endpoint ?? "",
    enabled: provider.enabled,
  };
}

function formStatusLabel(result: ProviderConnectivityResult): string {
  const segments = [
    result.ok ? "连接成功" : "连接失败",
    `${result.latency_ms}ms`,
    result.model_id ?? "",
    result.ok ? "" : result.detail,
    result.error_code && !result.ok ? `error_code=${result.error_code}` : "",
  ].filter((segment) => segment.length > 0);
  return segments.join(" · ");
}

export function ProvidersPage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [providers, setProviders] = useState<ProviderConfigView[]>([]);
  const [loadState, setLoadState] = useState<"error" | "loading" | "ready">("loading");
  const [status, setStatus] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [formMode, setFormMode] = useState<ProviderFormMode | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<ProviderFormState>(EMPTY_PROVIDER_FORM);
  const [revealKey, setRevealKey] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ProviderConfigView | null>(null);
  const [testTarget, setTestTarget] = useState<ProviderConfigView | null>(null);
  const [candidateKey, setCandidateKey] = useState("");

  useEffect(() => {
    let active = true;
    if (!accessToken) {
      setLoadState("error");
      setStatus("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    configureAdminProviderClient();
    void fetchProviders({ accessToken })
      .then((items) => {
        if (!active) return;
        setProviders(items);
        setLoadState("ready");
      })
      .catch((error: unknown) => {
        if (!active) return;
        setStatus(error instanceof Error ? error.message : "Provider 配置加载失败");
        setLoadState("error");
      });
    return () => {
      active = false;
    };
  }, [accessToken]);

  function openCreate() {
    setFormMode("create");
    setEditingId(null);
    setForm(EMPTY_PROVIDER_FORM);
    setRevealKey(false);
  }

  function openEdit(provider: ProviderConfigView) {
    setFormMode("edit");
    setEditingId(provider.id);
    setForm(formFromProvider(provider));
    setRevealKey(false);
  }

  function closeForm() {
    setFormMode(null);
    setEditingId(null);
    setForm(EMPTY_PROVIDER_FORM);
    setRevealKey(false);
  }

  async function submitForm(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !formMode) return;
    // API key handling: required on create, optional on edit (omit to keep the
    // stored key — never send an empty string).
    const endpointValue = form.endpoint.trim() || null;
    setBusyId(editingId ?? "__new__");
    try {
      if (formMode === "create") {
        if (form.api_key.length < 8) {
          setStatus("API Key 至少 8 个字符");
          return;
        }
        const created = await createProvider(
          {
            provider_type: form.provider_type,
            vendor: form.vendor.trim(),
            model: form.model.trim(),
            api_key: form.api_key,
            endpoint: endpointValue,
            params: {},
            enabled: form.enabled,
          },
          {
            accessToken,
            idempotencyKey: commandKey("provider-create"),
          },
        );
        setProviders((current) => [...current, created]);
        setStatus(`${created.vendor} 已创建 · 密钥已加密保存`);
      } else if (formMode === "edit" && editingId) {
        const updated = await updateProvider(
          editingId,
          {
            vendor: form.vendor.trim(),
            model: form.model.trim(),
            endpoint: endpointValue,
            enabled: form.enabled,
            ...(form.api_key.length > 0 ? { api_key: form.api_key } : {}),
          },
          {
            accessToken,
            idempotencyKey: commandKey("provider-update"),
          },
        );
        setProviders((current) =>
          current.map((provider) => (provider.id === editingId ? updated : provider)),
        );
        setStatus(`${updated.vendor} 已更新 · 版本 v${updated.version}`);
      }
      closeForm();
    } catch (error) {
      setStatus(providerApiError(error, "Provider 保存失败，请稍后重试"));
    } finally {
      setBusyId(null);
    }
  }

  async function toggleProvider(provider: ProviderConfigView, action: "disable" | "enable") {
    if (!accessToken) return;
    setBusyId(provider.id);
    configureAdminProviderClient();
    try {
      const headers = {
        accessToken,
        idempotencyKey: commandKey(`provider-${action}`),
      };
      const updated =
        action === "enable"
          ? await enableProvider(provider.id, headers)
          : await disableProvider(provider.id, headers);
      setProviders((current) =>
        current.map((item) => (item.id === provider.id ? updated : item)),
      );
      setStatus(`${updated.vendor} 已${action === "enable" ? "启用" : "停用"} · 版本 v${updated.version}`);
    } catch (error) {
      setStatus(providerApiError(error, "Provider 状态切换失败，请稍后重试"));
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete() {
    if (!accessToken || !deleteTarget) return;
    setBusyId(deleteTarget.id);
    configureAdminProviderClient();
    try {
      await deleteProvider(deleteTarget.id, {
        accessToken,
        idempotencyKey: commandKey("provider-delete"),
      });
      setProviders((current) => current.filter((item) => item.id !== deleteTarget.id));
      setStatus(`${deleteTarget.vendor} 已软删除 · 审计已记录`);
      setDeleteTarget(null);
    } catch (error) {
      setStatus(providerApiError(error, "Provider 删除失败，请稍后重试"));
    } finally {
      setBusyId(null);
    }
  }

  async function runTest(
    provider: ProviderConfigView,
    candidate?: string,
  ): Promise<void> {
    if (!accessToken) return;
    setBusyId(provider.id);
    configureAdminProviderClient();
    setStatus(`正在测试 ${provider.vendor}…`);
    try {
      const result = await testProviderConnectivity({
        accessToken,
        providerId: provider.id,
        candidateApiKey: candidate && candidate.length > 0 ? candidate : undefined,
      });
      setStatus(`${provider.vendor} · ${formStatusLabel(result)}`);
    } catch (error) {
      setStatus(providerApiError(error, "Provider 连通性测试失败，请稍后重试"));
    } finally {
      setBusyId(null);
    }
  }

  async function runCandidateTest(): Promise<void> {
    if (!testTarget) return;
    await runTest(testTarget, candidateKey);
    setTestTarget(null);
    setCandidateKey("");
  }

  return (
    <div className="admin-page">
      <AdminPageHeading
        action={
          <button className="admin-filter-button" onClick={openCreate} type="button">
            <Plus size={16} /> 新建 Provider
          </button>
        }
        description="System Admin 可创建、编辑、启停与软删除 Provider；密钥仅可替换，从不以明文返回"
        eyebrow="PROVIDER CRUD · BE-019"
        title="Provider 配置"
      />
      <OperationsNav />
      {status ? (
        <p aria-label="Provider 测试状态" className="admin-inline-status" role="status">
          {status}
        </p>
      ) : null}
      <section className="admin-panel admin-table-panel">
        {loadState === "loading" ? <p role="status">正在加载 Provider 配置…</p> : null}
        {loadState === "error" && !providers.length ? (
          <p role="alert">Provider 配置加载失败</p>
        ) : null}
        <table aria-label="Provider 配置" className="admin-data-table">
          <thead>
            <tr>
              <th>Provider</th>
              <th>能力</th>
              <th>密钥</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {providers.map((provider) => (
              <tr key={provider.id}>
                <th scope="row">
                  <strong>{provider.vendor}</strong>
                  <small>
                    {provider.model} · v{provider.version}
                  </small>
                </th>
                <td>{provider.provider_type}</td>
                <td>
                  <code>{provider.api_key_masked}</code>
                </td>
                <td>
                  <span className={`admin-badge is-${provider.enabled ? "active" : "paused"}`}>
                    {provider.enabled ? "ACTIVE" : "DISABLED"}
                  </span>
                </td>
                <td>
                  <div className="admin-row-actions">
                    <button
                      aria-label={`编辑${provider.vendor} Provider`}
                      className="admin-table-action"
                      disabled={busyId === provider.id}
                      onClick={() => openEdit(provider)}
                      type="button"
                    >
                      <PencilSimple size={14} /> 编辑
                    </button>
                    {provider.enabled ? (
                      <button
                        aria-label={`停用${provider.vendor} Provider`}
                        className="admin-table-action"
                        disabled={busyId === provider.id}
                        onClick={() => void toggleProvider(provider, "disable")}
                        type="button"
                      >
                        <Power size={14} /> 停用
                      </button>
                    ) : (
                      <button
                        aria-label={`启用${provider.vendor} Provider`}
                        className="admin-table-action"
                        disabled={busyId === provider.id}
                        onClick={() => void toggleProvider(provider, "enable")}
                        type="button"
                      >
                        <Power size={14} /> 启用
                      </button>
                    )}
                    <button
                      aria-label={`测试${provider.vendor} 连通性`}
                      className="admin-table-action"
                      disabled={busyId === provider.id}
                      onClick={() => void runTest(provider)}
                      type="button"
                    >
                      <LinkSimple size={14} /> 测试连接
                    </button>
                    <button
                      aria-label={`用候选密钥测试${provider.vendor} 连通性`}
                      className="admin-table-action"
                      disabled={busyId === provider.id}
                      onClick={() => {
                        setTestTarget(provider);
                        setCandidateKey("");
                      }}
                      type="button"
                    >
                      <LinkSimple size={14} /> 候选测试
                    </button>
                    <button
                      aria-label={`删除${provider.vendor} Provider`}
                      className="admin-table-action is-danger"
                      disabled={busyId === provider.id}
                      onClick={() => setDeleteTarget(provider)}
                      type="button"
                    >
                      <Trash size={14} /> 删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="admin-authority-note">
          <ShieldCheck size={15} /> Provider 密钥由后端加密保存（AES-GCM），所有响应仅返回
          mask · 每次写入携带 Idempotency-Key 并记入审计 · 仅 System Admin 可访问。
        </p>
      </section>
      {formMode ? (
        <ProviderFormDialog
          busy={busyId === "__new__"}
          form={form}
          mode={formMode}
          onClose={closeForm}
          onFormChange={setForm}
          onSubmit={submitForm}
          onToggleReveal={() => setRevealKey((current) => !current)}
          revealKey={revealKey}
        />
      ) : null}
      {testTarget ? (
        <ProviderTestDialog
          busy={busyId === testTarget.id}
          candidateKey={candidateKey}
          onCandidateKeyChange={setCandidateKey}
          onClose={() => {
            setTestTarget(null);
            setCandidateKey("");
          }}
          onSubmit={() => void runCandidateTest()}
          provider={testTarget}
        />
      ) : null}
      {deleteTarget ? (
        <div className="admin-dialog-backdrop">
          <section
            aria-labelledby="provider-delete-title"
            aria-modal="true"
            className="admin-confirm-dialog"
            role="dialog"
            aria-label="确认删除 Provider"
          >
            <p className="eyebrow">SOFT DELETE</p>
            <h2 id="provider-delete-title">确认删除 Provider</h2>
            <p>
              将软删除 <strong>{deleteTarget.vendor}</strong>（{deleteTarget.model}）：行会保留以
              维持审计与调用历史，仅 <code>enabled</code> 置为 false。此操作受审计且幂等。
            </p>
            <div>
              <button onClick={() => setDeleteTarget(null)} type="button">
                取消
              </button>
              <button
                className="is-danger"
                disabled={busyId === deleteTarget.id}
                onClick={() => void confirmDelete()}
                type="button"
              >
                确认删除
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

function ProviderFormDialog({
  busy,
  form,
  mode,
  onClose,
  onFormChange,
  onSubmit,
  onToggleReveal,
  revealKey,
}: {
  busy: boolean;
  form: ProviderFormState;
  mode: ProviderFormMode;
  onClose: () => void;
  onFormChange: (next: ProviderFormState) => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  onToggleReveal: () => void;
  revealKey: boolean;
}) {
  // The api_key field NEVER displays a stored value. On edit it starts empty
  // and the field label explicitly says "留空则保留原密钥". The reveal toggle
  // only changes the input type of what the user is currently typing — the
  // masked form from the server is shown separately and is the only key
  // representation that ever persists in the DOM.
  const maskedHint =
    mode === "edit" ? "留空则保留已加密保存的原密钥" : "至少 8 个字符，提交后由后端加密保存";

  // FE-016 presets: known-good starting points for recognized vendors. The
  // apply button fills product/model/endpoint (and provider_type when needed)
  // but NEVER touches api_key or enabled — admin stays in control and can
  // freely override every field after the preset is applied.
  const presetsForVendor = findPresetsForVendor(form.vendor);
  const hasPresets = presetsForVendor.length > 0;
  // When a vendor exposes multiple presets, the dialog renders a dropdown so
  // the admin can choose which capability (LLM/TTS/...) to apply. The default
  // tracks the preset that matches the form's current provider_type.
  const defaultPresetLabel = pickPresetForVendor(form.vendor, form.provider_type)?.label ?? "";
  const [selectedPresetLabel, setSelectedPresetLabel] = useState(defaultPresetLabel);
  // If the vendor changes (e.g. xfyun -> openai), re-sync the local dropdown
  // value to the new vendor's default preset. useEffect keeps this resilient
  // to type changes too.
  useEffect(() => {
    setSelectedPresetLabel(defaultPresetLabel);
  }, [defaultPresetLabel]);
  function applyPreset(preset: ProviderPreset): void {
    onFormChange({
      ...form,
      provider_type: preset.provider_type,
      // `product` is advisory metadata for the preset; the form has no
      // separate product field, so we keep `vendor` as the user typed it
      // (the preset does not rename their vendor identifier).
      model: preset.model,
      endpoint: preset.endpoint,
      // api_key + enabled intentionally NOT touched.
    });
  }
  return (
    <div className="admin-dialog-backdrop">
      <section
        aria-modal="true"
        className="admin-confirm-dialog admin-provider-form"
        role="dialog"
        aria-label={mode === "create" ? "新建 Provider 配置" : "编辑 Provider 配置"}
      >
        <p className="eyebrow">{mode === "create" ? "CREATE" : "UPDATE"}</p>
        <h2>{mode === "create" ? "新建 Provider 配置" : "编辑 Provider 配置"}</h2>
        <p>
          密钥以 AES-GCM 加密存储，所有响应仅返回 mask。System Admin 写入均记入审计且幂等。
        </p>
        <form onSubmit={onSubmit}>
          <label htmlFor="provider-vendor">Vendor</label>
          <input
            id="provider-vendor"
            onChange={(event) => onFormChange({ ...form, vendor: event.target.value })}
            pattern="[A-Za-z0-9._-]+"
            required
            value={form.vendor}
          />
          {hasPresets ? (
            <div className="admin-provider-presets">
              {presetsForVendor.length === 1 ? (
                <button
                  aria-label="应用预设"
                  className="admin-provider-preset-apply"
                  onClick={() => {
                    const preset = presetsForVendor[0];
                    if (preset) applyPreset(preset);
                  }}
                  type="button"
                >
                  <Lightning size={14} /> 应用预设
                </button>
              ) : (
                <div className="admin-provider-preset-row">
                  <label className="admin-provider-preset-select-label" htmlFor="provider-preset">
                    预设
                  </label>
                  <select
                    id="provider-preset"
                    onChange={(event) => setSelectedPresetLabel(event.target.value)}
                    value={selectedPresetLabel}
                  >
                    {presetsForVendor.map((preset) => (
                      <option key={preset.label} value={preset.label}>
                        {preset.label}
                      </option>
                    ))}
                  </select>
                  <button
                    aria-label="应用预设"
                    className="admin-provider-preset-apply"
                    onClick={() => {
                      const chosen =
                        presetsForVendor.find((p) => p.label === selectedPresetLabel) ??
                        presetsForVendor[0];
                      if (chosen) applyPreset(chosen);
                    }}
                    type="button"
                  >
                    <Lightning size={14} /> 应用预设
                  </button>
                </div>
              )}
              <small className="admin-provider-field-hint">
                预设值可编辑（仅起始值，并非官方验证；端点/模型可能随供应商更新而变化）。
              </small>
            </div>
          ) : null}
          <label htmlFor="provider-model">模型</label>
          <input
            id="provider-model"
            onChange={(event) => onFormChange({ ...form, model: event.target.value })}
            pattern="[A-Za-z0-9._:/-]+"
            required
            value={form.model}
          />
          <label htmlFor="provider-type">类型</label>
          <select
            id="provider-type"
            onChange={(event) =>
              onFormChange({ ...form, provider_type: event.target.value as ProviderType })
            }
            value={form.provider_type}
          >
            {PROVIDER_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
          <label htmlFor="provider-endpoint">Endpoint</label>
          <input
            id="provider-endpoint"
            onChange={(event) => onFormChange({ ...form, endpoint: event.target.value })}
            placeholder="https://provider.example.test/v1"
            value={form.endpoint}
          />
          <div className="admin-provider-field-row">
            <label htmlFor="provider-api-key">API Key</label>
            <button
              aria-label={revealKey ? "隐藏 API Key" : "显示 API Key"}
              className="admin-provider-reveal"
              onClick={onToggleReveal}
              type="button"
            >
              {revealKey ? <EyeSlash size={14} /> : <Eye size={14} />}
              {revealKey ? "隐藏" : "显示"}
            </button>
          </div>
          <input
            autoComplete="off"
            id="provider-api-key"
            minLength={mode === "create" ? 8 : undefined}
            onChange={(event) => onFormChange({ ...form, api_key: event.target.value })}
            placeholder={maskedHint}
            required={mode === "create"}
            type={revealKey ? "text" : "password"}
            value={form.api_key}
          />
          <small className="admin-provider-field-hint">{maskedHint}</small>
          <label className="admin-provider-toggle" htmlFor="provider-enabled">
            <input
              checked={form.enabled}
              id="provider-enabled"
              onChange={(event) => onFormChange({ ...form, enabled: event.target.checked })}
              type="checkbox"
            />
            启用（同类型仅一个可启用，后端按 §17.4 切换）
          </label>
          <div>
            <button onClick={onClose} type="button">
              取消
            </button>
            <button className="is-primary" disabled={busy} type="submit">
              {busy ? "保存中…" : "保存 Provider"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

function ProviderTestDialog({
  busy,
  candidateKey,
  onCandidateKeyChange,
  onClose,
  onSubmit,
  provider,
}: {
  busy: boolean;
  candidateKey: string;
  onCandidateKeyChange: (next: string) => void;
  onClose: () => void;
  onSubmit: () => void;
  provider: ProviderConfigView;
}) {
  return (
    <div className="admin-dialog-backdrop">
      <section
        aria-modal="true"
        className="admin-confirm-dialog"
        role="dialog"
        aria-label="测试 Provider 连通性"
      >
        <p className="eyebrow">CONNECTIVITY TEST</p>
        <h2>测试 Provider 连通性</h2>
        <p>
          对 <strong>{provider.vendor}</strong>（{provider.model}）执行一次有界的连通性探针。
          候选密钥（如填写）仅用于本次探针，不会被持久化或回显；留空则测试当前已保存的密钥。
        </p>
        <label htmlFor="provider-candidate-key">候选 API Key（可选）</label>
        <input
          autoComplete="off"
          id="provider-candidate-key"
          minLength={8}
          onChange={(event) => onCandidateKeyChange(event.target.value)}
          placeholder="留空测试已保存密钥；填写则以候选密钥探针（不入库）"
          type="password"
          value={candidateKey}
        />
        <div>
          <button onClick={onClose} type="button">
            取消
          </button>
          <button
            className="is-primary"
            disabled={busy}
            onClick={onSubmit}
            type="button"
          >
            {busy ? "测试中…" : "运行测试"}
          </button>
        </div>
      </section>
    </div>
  );
}

export function HealthPage({
  onHealthChange,
}: {
  onHealthChange?: (health: AdminSystemHealthView | null) => void;
} = {}) {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [searchParams] = useSearchParams();
  const [health, setHealth] = useState<AdminSystemHealthView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!accessToken) {
      setError("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    configureOperationsClient();
    void adminSystemHealthApiV1AdminSystemHealthGet({
      headers: { Authorization: `Bearer ${accessToken}` },
    })
      .then((result) => {
        if (!active) return;
        if (!result.data) throw new Error(operationsError(result.error));
        setHealth(result.data);
        onHealthChange?.(result.data);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : operationsError(caught));
        onHealthChange?.(null);
      });
    return () => {
      active = false;
    };
  }, [accessToken, onHealthChange]);

  if (searchParams.get("view") === "loading")
    return (
      <StatePanel
        description="正在检查 API、Worker、沙箱与数据服务"
        state="loading"
        title="加载系统健康状态"
      />
    );
  const degraded = searchParams.get("view") === "degraded" || health?.status === "DEGRADED";
  return (
    <div className="admin-page">
      <AdminPageHeading description="查看核心服务、队列、延迟与降级边界" title="运行监控" />
      <OperationsNav />
      {!health && !error ? <p role="status">正在加载系统健康状态…</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {degraded ? (
        <section aria-label="服务降级" className="admin-health-alert" role="alert">
          <WarningCircle size={20} />
          <div>
            <strong>系统当前存在降级组件</strong>
            <p>请检查下方组件详情；未受影响的功能会继续服务。</p>
          </div>
        </section>
      ) : null}
      <ul aria-label="服务健康状态" className="health-grid">
        {health?.components.map((component) => (
          <li key={component.component}>
            <span className={`health-dot is-${component.status.toLowerCase()}`} />
            <div>
              <strong>{component.component}</strong>
              <small>
                {component.detail} · {component.latency_ms}ms
              </small>
            </div>
            <span>{component.status}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function MetricsPage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;

  // In-page Course Admin guard. The route already enforces admin role via
  // `RequireAdmin`; this defends in depth so a future route refactor or a
  // shared embedding cannot leak advanced metrics to a non-admin session.
  if (!accessToken || session?.role !== "admin") {
    return (
      <StatePanel
        description="高级指标仅对授权管理员开放，请使用管理员账号登录"
        state="error"
        title="无权访问高级指标"
      />
    );
  }

  return <MetricsPageBody accessToken={accessToken} />;
}

function MetricsPageBody({ accessToken }: { accessToken: string }) {
  const [metrics, setMetrics] = useState<ProviderMetricsView | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Advanced-chart filters. Draft values are committed on submit so the BE-028
  // request and the displayed "已筛选" summary stay in sync with the user's
  // confirmed selection (mirrors FE-026's resource-stats pattern).
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [nodeId, setNodeId] = useState("");
  const [courseId, setCourseId] = useState("");
  const [draft, setDraft] = useState({ courseId: "", nodeId: "", since: "", until: "" });
  const [reloadAttempt, setReloadAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    configureOperationsClient();
    void adminProviderMetricsApiV1AdminSystemMetricsGet({
      headers: { Authorization: `Bearer ${accessToken}` },
    })
      .then((result) => {
        if (!active) return;
        if (!result.data) throw new Error(operationsError(result.error));
        setMetrics(result.data);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : operationsError(caught));
      });
    return () => {
      active = false;
    };
  }, [accessToken]);

  const advancedQuery = useQuery({
    queryKey: [
      "admin",
      "metrics",
      "advanced",
      accessToken,
      draft.courseId,
      draft.nodeId,
      draft.since,
      draft.until,
      reloadAttempt,
    ],
    queryFn: () =>
      fetchAdminMetrics({
        accessToken,
        courseId: draft.courseId,
        nodeId: draft.nodeId,
        since: draft.since,
        until: draft.until,
      }),
    enabled: Boolean(accessToken),
    // The window aggregates change slowly; a 60s TTL keeps the charts
    // responsive without re-running the server-side bucketing on every
    // navigation. The manual retry covers interactive recovery.
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    retry: false,
  });

  function applyFilters() {
    setDraft({
      courseId: courseId.trim(),
      nodeId: nodeId.trim(),
      since,
      until,
    });
  }

  const calls = metrics?.items.reduce((total, item) => total + item.calls, 0) ?? 0;
  const errors = metrics?.items.reduce((total, item) => total + item.errors, 0) ?? 0;
  const rateLimited = metrics?.items.reduce((total, item) => total + item.rate_limited, 0) ?? 0;
  const p95 = Math.max(0, ...(metrics?.items.map((item) => item.p95_latency_ms) ?? []));
  const advanced: AdminMetrics | undefined = advancedQuery.data ?? undefined;
  const apiBuckets = advanced?.api_usage.buckets ?? [];
  const masteryCounts = advanced?.mastery_distribution.counts ?? {};
  const timelinePoints = advanced?.agent_timeline.points ?? [];

  function exportAdvancedCsv() {
    if (!advanced) return;
    const stamp = new Date().toISOString().slice(0, 10);
    const rows: (string | number)[][] = [];
    rows.push(["# api_usage", "", "", "", "", ""]);
    for (const bucket of apiBuckets) {
      rows.push([
        bucket.bucket_start,
        bucket.total,
        bucket.p50 === null ? "" : bucket.p50,
        bucket.p95 === null ? "" : bucket.p95,
        bucket.error_rate.toFixed(4),
        bucket.throttle_rate.toFixed(4),
      ]);
    }
    rows.push(["# mastery_distribution", "", "", "", "", ""]);
    for (const [status, count] of Object.entries(masteryCounts)) {
      rows.push([status, count ?? 0, "", "", "", ""]);
    }
    rows.push(["# agent_timeline", "", "", "", "", ""]);
    for (const point of timelinePoints) {
      rows.push([
        point.run_id,
        point.route,
        point.status,
        point.fallback ? "fallback" : "",
        point.latency_ms === null ? "" : point.latency_ms,
        point.started_at,
      ]);
    }
    downloadCsv(
      `pymentor-metrics-${stamp}.csv`,
      ["section_or_bucket", "total_or_count", "p50", "p95", "rate_or_flag", "extra"],
      rows,
    );
  }

  return (
    <div className="admin-page">
      <AdminPageHeading
        action={
          <button
            aria-label="导出指标 CSV"
            className="admin-filter-button"
            disabled={!advanced}
            onClick={() => exportAdvancedCsv()}
            type="button"
          >
            <DownloadSimple size={16} /> 导出指标 CSV
          </button>
        }
        description="API、沙箱与 Agent 的吞吐、错误率、延迟预算与高级图表"
        title="API 与作业指标"
      />
      <OperationsNav />
      {!metrics && !error ? <p role="status">正在加载 Provider 指标…</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      <section className="metric-grid">
        {(
          [
            ["Provider 调用", String(calls), "当前窗口"],
            ["P95 延迟", `${p95}ms`, "最慢 Provider"],
            ["错误数", String(errors), calls ? `${((errors / calls) * 100).toFixed(1)}%` : "0%"],
            ["限流次数", String(rateLimited), "当前窗口"],
          ] as const
        ).map(([label, value, note]) => (
          <article className="metric-card" key={label}>
            <p>{label}</p>
            <div>
              <strong>{value}</strong>
              <span>{note}</span>
            </div>
            <progress
              aria-label={`${label}预算使用`}
              max={100}
              value={Math.min(100, label === "错误数" && calls ? (errors / calls) * 100 : 48)}
            />
          </article>
        ))}
      </section>
      <ChartFrame
        columns={["Provider", "模型", "请求", "P95", "错误率"]}
        description="后端聚合的 Provider 调用量、延迟和错误率"
        rows={(metrics?.items ?? []).map((item) => [
          item.vendor,
          item.model,
          String(item.calls),
          `${item.p95_latency_ms}ms`,
          `${(item.error_rate * 100).toFixed(1)}%`,
        ])}
        title="Provider 指标"
      >
        <div className="admin-metric-bars">
          {(metrics?.items ?? []).map((item) => (
            <label key={`${item.vendor}-${item.model}`}>
              {item.vendor}
              <progress max={Math.max(1, calls)} value={item.calls} />
            </label>
          ))}
        </div>
      </ChartFrame>
      <section aria-label="高级指标筛选" className="admin-panel admin-panel--compact">
        <div className="admin-panel__heading">
          <div>
            <p className="eyebrow">ADVANCED METRICS · BE-028</p>
            <h2>高级图表筛选</h2>
          </div>
        </div>
        <form
          className="admin-table-toolbar"
          onSubmit={(event) => {
            event.preventDefault();
            applyFilters();
          }}
        >
          <label className="admin-filter-field">
            <Funnel size={16} />
            <span>起始日期</span>
            <input
              aria-label="起始日期"
              onChange={(event) => setSince(event.target.value)}
              type="date"
              value={since}
            />
          </label>
          <label className="admin-filter-field">
            <Funnel size={16} />
            <span>结束日期</span>
            <input
              aria-label="结束日期"
              onChange={(event) => setUntil(event.target.value)}
              type="date"
              value={until}
            />
          </label>
          <label className="admin-filter-field">
            <Funnel size={16} />
            <span>节点 ID</span>
            <input
              aria-label="节点 ID"
              onChange={(event) => setNodeId(event.target.value)}
              placeholder="可选，留空汇总所有节点"
              type="text"
              value={nodeId}
            />
          </label>
          <label className="admin-filter-field">
            <Funnel size={16} />
            <span>课程 ID</span>
            <input
              aria-label="课程 ID"
              onChange={(event) => setCourseId(event.target.value)}
              placeholder="可选，留空汇总所有课程"
              type="text"
              value={courseId}
            />
          </label>
          <button className="admin-filter-button" type="submit">
            <Funnel size={15} /> 应用筛选
          </button>
          {draft.since || draft.until || draft.nodeId || draft.courseId ? (
            <span>
              已筛选：{[draft.since, draft.until].filter(Boolean).join(" ~ ")}
              {draft.nodeId ? ` · 节点 ${draft.nodeId}` : ""}
              {draft.courseId ? ` · 课程 ${draft.courseId}` : ""}
            </span>
          ) : (
            <span>当前窗口：全租户汇总</span>
          )}
        </form>
      </section>
      {advancedQuery.isLoading || advancedQuery.isPending ? (
        <p aria-label="高级指标加载" className="admin-empty-row" role="status">
          正在加载高级指标…
        </p>
      ) : null}
      {advancedQuery.isError ? (
        <div aria-label="高级指标错误" className="admin-empty-row" role="alert">
          <p>
            {advancedQuery.error instanceof Error
              ? advancedQuery.error.message
              : "高级指标数据暂时不可用，请稍后重试"}
          </p>
          <button
            aria-label="重试高级指标"
            onClick={() => setReloadAttempt((attempt) => attempt + 1)}
            type="button"
          >
            重试
          </button>
        </div>
      ) : null}
      {advanced ? (
        <section aria-label="高级图表" className="admin-advanced-charts">
          <ApiUsageChart buckets={apiBuckets} />
          <MasteryDistributionChart counts={masteryCounts} />
          <AgentTimelineChart points={timelinePoints} />
          <p className="admin-authority-note">
            <ShieldCheck size={15} /> 高级图表为只读聚合；课程与租户隔离由 BE-028
            强制执行，空桶的延迟渲染为缺口而非零值。
          </p>
        </section>
      ) : null}
    </div>
  );
}

export function LogsPage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [level, setLevel] = useState("ALL");
  const [logs, setLogs] = useState<AdminLogPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setError(null);
    if (!accessToken) {
      setError("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    configureOperationsClient();
    void adminSystemLogsApiV1AdminSystemLogsGet({
      headers: { Authorization: `Bearer ${accessToken}` },
      query: { level: level === "ALL" ? undefined : level, page: 1, page_size: 50 },
    })
      .then((result) => {
        if (!active) return;
        if (!result.data) throw new Error(operationsError(result.error));
        setLogs(result.data);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : operationsError(caught));
      });
    return () => {
      active = false;
    };
  }, [accessToken, level]);

  return (
    <div className="admin-page">
      <AdminPageHeading
        description="结构化检索系统事件，不显示密钥、Cookie 或原始提示"
        title="系统日志"
      />
      <OperationsNav />
      <section className="admin-panel admin-table-panel">
        {!logs && !error ? <p role="status">正在加载结构化日志…</p> : null}
        {error ? <p role="alert">{error}</p> : null}
        <div className="admin-table-toolbar">
          <label>
            日志级别
            <select
              aria-label="日志级别"
              onChange={(event) => setLevel(event.target.value)}
              value={level}
            >
              <option value="ALL">全部</option>
              <option value="INFO">INFO</option>
              <option value="WARN">WARN</option>
              <option value="ERROR">ERROR</option>
            </select>
          </label>
          <span>保留 30 天 · 敏感字段已脱敏</span>
        </div>
        <table aria-label="系统日志" className="admin-data-table">
          <thead>
            <tr>
              <th>级别</th>
              <th>时间</th>
              <th>事件</th>
              <th>上下文</th>
            </tr>
          </thead>
          <tbody>
            {(logs?.items ?? []).map((item) => (
              <tr key={item.id}>
                <td>
                  <span className={`admin-badge is-${item.level.toLowerCase()}`}>{item.level}</span>
                </td>
                <td>{new Date(item.created_at).toLocaleString("zh-CN")}</td>
                <th scope="row">
                  <code>{item.message}</code>
                </th>
                <td>
                  {item.source} · {item.trace_id} · {JSON.stringify(item.context)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

type RiskOperation = "backup" | "restore";

export function DatabasePage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [database, setDatabase] = useState<DatabaseStatusView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [operation, setOperation] = useState<RiskOperation | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const phrase = operation === "backup" ? "BACKUP DATABASE" : "RESTORE DATABASE";

  useEffect(() => {
    let active = true;
    if (!accessToken) {
      setLoadError("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    configureOperationsClient();
    void databaseStatusApiV1AdminSystemDbGet({
      headers: { Authorization: `Bearer ${accessToken}` },
    })
      .then((result) => {
        if (!active) return;
        if (!result.data) throw new Error(operationsError(result.error));
        setDatabase(result.data);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setLoadError(caught instanceof Error ? caught.message : operationsError(caught));
      });
    return () => {
      active = false;
    };
  }, [accessToken]);

  async function submitMaintenance() {
    if (!accessToken || !operation || confirmation !== phrase) return;
    configureOperationsClient();
    const headers = {
      Authorization: `Bearer ${accessToken}`,
      "Idempotency-Key": commandKey(`database-${operation}`),
    };
    try {
      if (operation === "backup") {
        const result = await createDatabaseBackupApiV1AdminSystemDbBackupPost({
          body: { confirmation },
          headers,
        });
        if (!result.data) throw new Error(operationsError(result.error));
        setDatabase((current) => (current ? { ...current, last_backup: result.data } : current));
        setStatus(`备份已创建 · ${result.data.id} · ${formatBytes(result.data.size_bytes)}`);
      } else {
        const backupId = database?.last_backup?.id;
        if (!backupId) throw new Error("没有可恢复的已验证备份");
        const result = await restoreDatabaseBackupApiV1AdminSystemDbRestorePost({
          body: { backup_id: backupId, confirmation },
          headers,
        });
        if (!result.data) throw new Error(operationsError(result.error));
        setStatus(`恢复已完成 · ${result.data.id} · ${result.data.status}`);
      }
      setOperation(null);
      setConfirmation("");
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : operationsError(caught));
    }
  }

  return (
    <div className="admin-page">
      <AdminPageHeading
        description="备份、恢复、导出与数据清理均写入高风险操作审计"
        title="数据运维"
      />
      <OperationsNav />
      {!database && !loadError ? <p role="status">正在加载数据库状态…</p> : null}
      {loadError ? <p role="alert">{loadError}</p> : null}
      {status ? (
        <p aria-label="数据库操作状态" className="admin-inline-status" role="status">
          {status}
        </p>
      ) : null}
      <section className="metric-grid">
        <article className="metric-card">
          <p>数据库大小</p>
          <div>
            <strong>{formatBytes(database?.database_size_bytes ?? 0)}</strong>
            <span>{database?.engine ?? "等待后端"}</span>
          </div>
        </article>
        <article className="metric-card">
          <p>最近备份</p>
          <div>
            <strong>
              {database?.last_backup
                ? new Date(database.last_backup.created_at).toLocaleString("zh-CN")
                : "暂无"}
            </strong>
            <span>{database?.last_backup?.status ?? "未创建备份"}</span>
          </div>
        </article>
        <article className="metric-card">
          <p>Schema</p>
          <div>
            <strong>{database?.schema_revision ?? "未知"}</strong>
            <span>{database?.table_count ?? 0} 张表</span>
          </div>
        </article>
        <article className="metric-card">
          <p>活动连接</p>
          <div>
            <strong>{database?.active_connections ?? 0}</strong>
            <span>慢查询 {database?.slow_query_count ?? 0}</span>
          </div>
        </article>
      </section>
      <section className="admin-panel admin-panel--compact data-operations">
        <div className="admin-panel__heading">
          <div>
            <p className="eyebrow">CONTROLLED OPERATIONS</p>
            <h2>数据操作</h2>
          </div>
        </div>
        <div>
          <article>
            <span>
              <DownloadSimple size={20} />
            </span>
            <div>
              <strong>创建数据库备份</strong>
              <p>生成校验摘要并写入私有、版本化对象存储。</p>
            </div>
            <button
              aria-label="创建数据库备份"
              onClick={() => {
                setOperation("backup");
                setConfirmation("");
              }}
              type="button"
            >
              创建备份
            </button>
          </article>
          <article>
            <span>
              <HardDrives size={20} />
            </span>
            <div>
              <strong>恢复最近备份</strong>
              <p>创建异步恢复任务，执行前需精确确认。</p>
            </div>
            <button
              aria-label="恢复备份"
              disabled={!database?.last_backup}
              onClick={() => {
                setOperation("restore");
                setConfirmation("");
              }}
              type="button"
            >
              恢复备份
            </button>
          </article>
        </div>
      </section>
      {operation ? (
        <div className="admin-dialog-backdrop">
          <section
            aria-labelledby="database-confirm-title"
            aria-modal="true"
            className="admin-confirm-dialog"
            role="dialog"
          >
            <p className="eyebrow">HIGH-RISK OPERATION</p>
            <h2 id="database-confirm-title">
              {operation === "restore" ? "确认恢复数据库" : "确认创建数据库备份"}
            </h2>
            <p>确认后由后端执行幂等、受审计的维护命令；浏览器不会接触数据库凭据。</p>
            <label htmlFor="database-confirmation">
              输入确认短语 <code>{phrase}</code>
            </label>
            <input
              aria-label="输入确认短语"
              id="database-confirmation"
              onChange={(event) => setConfirmation(event.target.value)}
              value={confirmation}
            />
            <div>
              <button
                aria-label={operation === "restore" ? "取消恢复" : "取消备份"}
                onClick={() => setOperation(null)}
                type="button"
              >
                取消
              </button>
              <button
                className="is-danger"
                disabled={confirmation !== phrase}
                onClick={() => void submitMaintenance()}
                type="button"
              >
                {operation === "restore" ? "确认恢复" : "确认备份"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

export function AuditPage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [auditLogs, setAuditLogs] = useState<AdminLogPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setError(null);
    if (!accessToken) {
      setError("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    configureOperationsClient();
    void adminSystemLogsApiV1AdminSystemLogsGet({
      headers: { Authorization: `Bearer ${accessToken}` },
      query: { page: 1, page_size: 50, source: "AUDIT" },
    })
      .then((result) => {
        if (!active) return;
        if (!result.data) throw new Error(operationsError(result.error));
        setAuditLogs(result.data);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : operationsError(caught));
      });
    return () => {
      active = false;
    };
  }, [accessToken]);

  return (
    <div className="admin-page">
      <AdminPageHeading description="检索认证、审核、Agent 与高风险数据操作" title="系统审计" />
      <section className="admin-panel admin-table-panel">
        {!auditLogs && !error ? <p role="status">正在加载不可变审计记录…</p> : null}
        {error ? <p role="alert">{error}</p> : null}
        <div className="admin-table-toolbar">
          <strong>不可变审计记录</strong>
          <span>审计投影只读 · 敏感字段已脱敏</span>
        </div>
        <table aria-label="系统审计记录" className="admin-data-table">
          <thead>
            <tr>
              <th>事件</th>
              <th>来源</th>
              <th>Trace</th>
              <th>安全上下文</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            {(auditLogs?.items ?? []).map((item) => (
              <tr key={item.id}>
                <th scope="row">
                  <code>{item.message}</code>
                </th>
                <td>{item.source}</td>
                <td>
                  <code>{item.trace_id}</code>
                </td>
                <td>{JSON.stringify(item.context)}</td>
                <td>{new Date(item.created_at).toLocaleString("zh-CN")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
