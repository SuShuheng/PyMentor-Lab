import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle,
  Database,
  DownloadSimple,
  Funnel,
  Gauge,
  HardDrives,
  LinkSimple,
  MagnifyingGlass,
  ShieldCheck,
  Student,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { ChartFrame } from "@pymentor/charts";
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
  listProvidersApiV1AdminProvidersGet,
  listPendingApiV1AdminRegistrationsPendingGet,
  type ProviderMetricsView,
  rejectRegistrationApiV1AdminRegistrationsUserIdRejectPost,
  restoreDatabaseBackupApiV1AdminSystemDbRestorePost,
  type PendingRegistration,
  type ProviderConfigView,
  testProviderConnectivityApiV1AdminProvidersProviderIdTestPost,
} from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";
import { StatePanel } from "@pymentor/ui";
import { useEffect, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";

import { useAdminAuth } from "../auth/auth-session";

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

export function OverviewPage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [registrations, setRegistrations] = useState<PendingRegistration[]>([]);
  const [queueState, setQueueState] = useState<"error" | "loading" | "ready">("loading");
  const [queueError, setQueueError] = useState<string | null>(null);
  const [reloadAttempt, setReloadAttempt] = useState(0);
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [reviewStatus, setReviewStatus] = useState<string | null>(null);

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
        {[
          ["活跃学生", "248", "+12 本周"],
          ["待审核注册", String(registrations.length), "需人工处理"],
          ["资源审校", "7", "2 项高优先级"],
          ["服务健康", "7 / 8", "图像服务降级"],
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

export function ProvidersPage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [providers, setProviders] = useState<ProviderConfigView[]>([]);
  const [loadState, setLoadState] = useState<"error" | "loading" | "ready">("loading");
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!accessToken) {
      setLoadState("error");
      setStatus("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    configureOperationsClient();
    void listProvidersApiV1AdminProvidersGet({
      headers: { Authorization: `Bearer ${accessToken}` },
    })
      .then((result) => {
        if (!active) return;
        if (!result.data) throw new Error(operationsError(result.error));
        setProviders(result.data.items);
        setLoadState("ready");
      })
      .catch((error: unknown) => {
        if (!active) return;
        setStatus(error instanceof Error ? error.message : operationsError(error));
        setLoadState("error");
      });
    return () => {
      active = false;
    };
  }, [accessToken]);

  async function testConnectivity(provider: ProviderConfigView) {
    if (!accessToken) return;
    setStatus(`正在测试 ${provider.vendor}…`);
    configureOperationsClient();
    try {
      const result = await testProviderConnectivityApiV1AdminProvidersProviderIdTestPost({
        headers: { Authorization: `Bearer ${accessToken}` },
        path: { provider_id: provider.id },
      });
      if (!result.data) throw new Error(operationsError(result.error));
      setStatus(
        result.data.ok
          ? `${provider.vendor} 连接成功 · ${result.data.latency_ms}ms · 未返回任何密钥`
          : `${provider.vendor} 连接失败 · ${result.data.detail}`,
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : operationsError(error));
    }
  }

  return (
    <div className="admin-page">
      <AdminPageHeading description="密钥仅可替换，不从 API 返回明文" title="Provider 配置" />
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
                  <small>{provider.model}</small>
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
                  <button
                    aria-label={`测试${provider.vendor} 连通性`}
                    className="admin-table-action"
                    onClick={() => void testConnectivity(provider)}
                    type="button"
                  >
                    <LinkSimple size={14} /> 测试连接
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="admin-authority-note">
          <ShieldCheck size={15} /> Provider 密钥由后端加密保存，Renderer 永不持有明文。
        </p>
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
  const [metrics, setMetrics] = useState<ProviderMetricsView | null>(null);
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

  const calls = metrics?.items.reduce((total, item) => total + item.calls, 0) ?? 0;
  const errors = metrics?.items.reduce((total, item) => total + item.errors, 0) ?? 0;
  const rateLimited = metrics?.items.reduce((total, item) => total + item.rate_limited, 0) ?? 0;
  const p95 = Math.max(0, ...(metrics?.items.map((item) => item.p95_latency_ms) ?? []));
  return (
    <div className="admin-page">
      <AdminPageHeading
        description="API、沙箱与 Agent 的吞吐、错误率和延迟预算"
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
