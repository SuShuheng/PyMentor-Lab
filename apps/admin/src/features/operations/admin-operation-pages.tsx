import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle,
  Clock,
  Database,
  DownloadSimple,
  Funnel,
  Gauge,
  HardDrives,
  Key,
  LinkSimple,
  MagnifyingGlass,
  Pulse,
  ShieldCheck,
  Student,
  Trash,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { ChartFrame } from "@pymentor/charts";
import {
  approveRegistrationApiV1AdminRegistrationsUserIdApprovePost,
  client,
  listPendingApiV1AdminRegistrationsPendingGet,
  rejectRegistrationApiV1AdminRegistrationsUserIdRejectPost,
  type PendingRegistration,
} from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";
import { StatePanel } from "@pymentor/ui";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";

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
  return "注册审核服务暂时不可用，请稍后重试";
}

function registrationLabel(registration: PendingRegistration): string {
  return registration.student_no || registration.email;
}

function commandKey(prefix: string): string {
  return `${prefix}-${globalThis.crypto.randomUUID()}`;
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

const students = [
  ["STU-2026001", "林晓", "Python 1 班", "ACTIVE", "12 / 20", "今天 10:42"],
  ["STU-2026002", "赵珂", "Python 1 班", "ACTIVE", "9 / 20", "今天 09:18"],
  ["STU-2026003", "周宁", "Python 2 班", "ACTIVE", "15 / 20", "昨天 21:04"],
  ["STU-2026004", "魏乔", "Python 2 班", "PAUSED", "7 / 20", "昨天 16:30"],
  ["STU-2026005", "唐夏", "Python 3 班", "ACTIVE", "11 / 20", "今天 11:06"],
  ["STU-2026006", "何川", "Python 3 班", "ACTIVE", "6 / 20", "3 天前"],
] as const;

export function StudentsPage() {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return keyword
      ? students.filter((row) => row.join(" ").toLowerCase().includes(keyword))
      : students;
  }, [query]);
  const pageSize = 2;
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const rows = filtered.slice((page - 1) * pageSize, page * pageSize);

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
            {query ? `筛选结果 ${filtered.length} 人` : `共 ${students.length} 人 · 服务端分页`}
          </span>
        </div>
        <div className="admin-table-scroll">
          <table aria-label="学生列表" className="admin-data-table">
            <thead>
              <tr>
                <th>学生</th>
                <th>班级</th>
                <th>状态</th>
                <th>稳定掌握</th>
                <th>最近活动</th>
                <th>
                  <span className="sr-only">操作</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([id, name, course, status, mastery, activity]) => (
                <tr key={id}>
                  <th scope="row">
                    <strong>{name}</strong>
                    <small>{id}</small>
                  </th>
                  <td>{course}</td>
                  <td>
                    <span className={`admin-badge is-${status.toLowerCase()}`}>{status}</span>
                  </td>
                  <td>{mastery}</td>
                  <td>{activity}</td>
                  <td>
                    <Link aria-label={`查看${name}的学习详情`} to={`/admin/students/${id}`}>
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
  return (
    <div className="admin-page">
      <AdminPageHeading
        action={
          <Link className="admin-filter-button" to="/admin/students">
            <ArrowLeft size={15} /> 返回学生列表
          </Link>
        }
        description="STU-2026001 · Python 程序设计 1 班 · Profile v3"
        title="林晓 · 学习详情"
      />
      <section aria-label="学生概览" className="metric-grid">
        {[
          ["稳定掌握", "12", "20 个节点"],
          ["初步掌握", "5", "等待复测"],
          ["到期复测", "1", "今天"],
          ["证据记录", "86", "最新 10:42"],
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
            <li>
              <CheckCircle size={18} weight="fill" />
              <div>
                <strong>条件分支 · STABLE_MASTERY</strong>
                <small>复测通过 · 2026-07-16</small>
              </div>
            </li>
            <li>
              <Clock size={18} />
              <div>
                <strong>循环边界 · INITIAL_MASTERY</strong>
                <small>到期复测：今天 23:59</small>
              </div>
            </li>
            <li>
              <Pulse size={18} />
              <div>
                <strong>函数基础 · LEARNING</strong>
                <small>当前路径节点</small>
              </div>
            </li>
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
              <tr>
                <th scope="row">EVD-1882</th>
                <td>隐藏测试</td>
                <td>边界值失败</td>
                <td>10:42</td>
              </tr>
              <tr>
                <th scope="row">EVD-1877</th>
                <td>Trace 预测</td>
                <td>关键帧正确</td>
                <td>10:36</td>
              </tr>
              <tr>
                <th scope="row">EVD-1844</th>
                <td>到期复测</td>
                <td>通过</td>
                <td>昨天</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}

const reviewResources = [
  ["RES-102", "循环边界微讲义", "v3.1", "KB-PY-04", "事实通过 · 合规通过"],
  ["RES-103", "函数参数结构卡", "v2.0", "KB-PY-05", "事实待复核 · 合规通过"],
] as const;

export function ResourceReviewPage() {
  const [status, setStatus] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  return (
    <div className="admin-page">
      <AdminPageHeading
        description="核对来源映射、事实性、合规性与版本差异后再发布"
        title="资源审核"
      />
      {status ? (
        <p aria-label="资源审核状态" className="admin-inline-status" role="status">
          {status}
        </p>
      ) : null}
      <section className="admin-panel admin-table-panel">
        <div className="admin-table-toolbar">
          <strong>待审校版本</strong>
          <span>2 项 · 发布门禁默认关闭</span>
        </div>
        <table aria-label="待审核资源" className="admin-data-table">
          <thead>
            <tr>
              <th>资源</th>
              <th>版本</th>
              <th>来源</th>
              <th>审校</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {reviewResources.map(([id, title, version, source, review]) => (
              <tr key={id}>
                <th scope="row">
                  <strong>{title}</strong>
                  <small>{id}</small>
                </th>
                <td>{version}</td>
                <td>{source}</td>
                <td>{review}</td>
                <td>
                  <div className="admin-row-actions">
                    <button
                      aria-label={`拒绝资源 ${id}`}
                      onClick={() => {
                        setRejecting(id);
                        setReason("");
                      }}
                      type="button"
                    >
                      拒绝
                    </button>
                    <button
                      aria-label={`批准资源 ${id}`}
                      className="is-primary"
                      onClick={() => setStatus(`${id} 已批准发布 · 审计记录已保存`)}
                      type="button"
                    >
                      批准
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {rejecting ? (
        <div className="admin-dialog-backdrop">
          <section
            aria-labelledby="reject-resource-title"
            aria-modal="true"
            className="admin-confirm-dialog"
            role="dialog"
          >
            <p className="eyebrow">REJECT RESOURCE</p>
            <h2 id="reject-resource-title">拒绝资源 {rejecting}</h2>
            <p>拒绝后不会发布此版本，上一审校通过版本保持可用。</p>
            <label htmlFor="reject-reason">拒绝原因</label>
            <textarea
              aria-label="拒绝原因"
              id="reject-reason"
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              value={reason}
            />
            <div>
              <button onClick={() => setRejecting(null)} type="button">
                取消
              </button>
              <button
                className="is-danger"
                disabled={!reason.trim()}
                onClick={() => {
                  setStatus(`${rejecting} 已拒绝 · ${reason}`);
                  setRejecting(null);
                }}
                type="button"
              >
                确认拒绝
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

export function ProvidersPage() {
  const [status, setStatus] = useState<string | null>(null);
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
            <tr>
              <th scope="row">
                <strong>讯飞 LLM</strong>
                <small>spark-compatible</small>
              </th>
              <td>对话 / Agent</td>
              <td>
                <code>••••••••7H2K</code>
              </td>
              <td>
                <span className="admin-badge is-active">ACTIVE</span>
              </td>
              <td>
                <button
                  aria-label="测试讯飞 LLM 连通性"
                  className="admin-table-action"
                  onClick={() => setStatus("讯飞 LLM 连接成功 · 428ms · 未返回任何密钥")}
                  type="button"
                >
                  <LinkSimple size={14} /> 测试连接
                </button>
              </td>
            </tr>
            <tr>
              <th scope="row">
                <strong>图像生成</strong>
                <small>image-v2</small>
              </th>
              <td>配图 / 图解</td>
              <td>
                <code>••••••••91QF</code>
              </td>
              <td>
                <span className="admin-badge is-paused">DEGRADED</span>
              </td>
              <td>
                <button className="admin-table-action" type="button">
                  <Key size={14} /> 替换密钥
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <p className="admin-authority-note">
          <ShieldCheck size={15} /> Provider 密钥由后端加密保存，Renderer 永不持有明文。
        </p>
      </section>
    </div>
  );
}

const services = [
  ["API", "HEALTHY", "41ms"],
  ["Agent Worker", "HEALTHY", "队列 3"],
  ["Sandbox", "HEALTHY", "88ms"],
  ["PostgreSQL", "HEALTHY", "14ms"],
  ["Redis", "HEALTHY", "6ms"],
  ["Object Storage", "HEALTHY", "31ms"],
  ["图像 Provider", "DEGRADED", "超时 18m"],
] as const;

export function HealthPage() {
  const [searchParams] = useSearchParams();
  if (searchParams.get("view") === "loading")
    return (
      <StatePanel
        description="正在检查 API、Worker、沙箱与数据服务"
        state="loading"
        title="加载系统健康状态"
      />
    );
  const degraded = searchParams.get("view") === "degraded";
  return (
    <div className="admin-page">
      <AdminPageHeading description="查看核心服务、队列、延迟与降级边界" title="运行监控" />
      <OperationsNav />
      {degraded ? (
        <section aria-label="服务降级" className="admin-health-alert" role="alert">
          <WarningCircle size={20} />
          <div>
            <strong>图像 Provider 当前降级</strong>
            <p>文字资源与 Notebook 不受影响；配图作业使用文字回退。</p>
          </div>
        </section>
      ) : null}
      <ul aria-label="服务健康状态" className="health-grid">
        {services.map(([name, state, detail]) => (
          <li key={name}>
            <span className={`health-dot is-${state.toLowerCase()}`} />
            <div>
              <strong>{name}</strong>
              <small>{detail}</small>
            </div>
            <span>{state}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function MetricsPage() {
  return (
    <div className="admin-page">
      <AdminPageHeading
        description="API、沙箱与 Agent 的吞吐、错误率和延迟预算"
        title="API 与作业指标"
      />
      <OperationsNav />
      <section className="metric-grid">
        {(
          [
            ["API P95", "182ms", "预算 500ms"],
            ["SSE 首字 P95", "1.8s", "预算 3s"],
            ["Sandbox P95", "1.2s", "预算 2s"],
            ["作业成功率", "98.7%", "24h"],
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
              value={label.includes("成功") ? 99 : 48}
            />
          </article>
        ))}
      </section>
      <ChartFrame
        columns={["端点", "请求", "P95", "错误率"]}
        description="最近 6 小时的服务端请求量、延迟和错误预算"
        rows={[
          ["/api/v1/tasks", "4,281", "164ms", "0.2%"],
          ["/api/v1/code-runs", "1,403", "1.2s", "1.1%"],
          ["/api/v1/tutor/stream", "926", "1.8s 首字", "0.8%"],
        ]}
        title="请求指标"
      >
        <div className="admin-metric-bars">
          <label>
            任务查询
            <progress max={5000} value={4281} />
          </label>
          <label>
            代码运行
            <progress max={5000} value={1403} />
          </label>
          <label>
            辅导流
            <progress max={5000} value={926} />
          </label>
        </div>
      </ChartFrame>
    </div>
  );
}

const logs = [
  ["INFO", "12:06:48", "worker.job.started", "JOB-RES-2407 · resource_pack"],
  ["WARN", "12:05:31", "provider.image.degraded", "fallback=text-only"],
  ["ERROR", "12:05:29", "provider.image.timeout", "request_id=req-88f2"],
] as const;

export function LogsPage() {
  const [level, setLevel] = useState("ALL");
  const rows = level === "ALL" ? logs : logs.filter((row) => row[0] === level);
  return (
    <div className="admin-page">
      <AdminPageHeading
        description="结构化检索系统事件，不显示密钥、Cookie 或原始提示"
        title="系统日志"
      />
      <OperationsNav />
      <section className="admin-panel admin-table-panel">
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
            {rows.map(([logLevel, time, event, context]) => (
              <tr key={event}>
                <td>
                  <span className={`admin-badge is-${logLevel.toLowerCase()}`}>{logLevel}</span>
                </td>
                <td>{time}</td>
                <th scope="row">
                  <code>{event}</code>
                </th>
                <td>{context}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

type RiskOperation = "restore" | "cleanup";

export function DatabasePage() {
  const [operation, setOperation] = useState<RiskOperation | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const phrase = operation === "cleanup" ? "DELETE DEMO DATA" : "RESTORE PYMENTOR";
  return (
    <div className="admin-page">
      <AdminPageHeading
        description="备份、恢复、导出与数据清理均写入高风险操作审计"
        title="数据运维"
      />
      <OperationsNav />
      {status ? (
        <p aria-label="数据库操作状态" className="admin-inline-status" role="status">
          {status}
        </p>
      ) : null}
      <section className="metric-grid">
        <article className="metric-card">
          <p>数据库大小</p>
          <div>
            <strong>2.8 GB</strong>
            <span>PostgreSQL</span>
          </div>
        </article>
        <article className="metric-card">
          <p>最近备份</p>
          <div>
            <strong>03:00</strong>
            <span>校验通过</span>
          </div>
        </article>
        <article className="metric-card">
          <p>RPO</p>
          <div>
            <strong>24h</strong>
            <span>竞赛环境</span>
          </div>
        </article>
        <article className="metric-card">
          <p>对象存储</p>
          <div>
            <strong>18.4 GB</strong>
            <span>版本化</span>
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
              <strong>导出审计数据</strong>
              <p>生成脱敏 CSV，不包含 Provider 密钥。</p>
            </div>
            <button onClick={() => setStatus("脱敏导出任务已创建")} type="button">
              创建导出
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
              onClick={() => {
                setOperation("restore");
                setConfirmation("");
              }}
              type="button"
            >
              恢复备份
            </button>
          </article>
          <article>
            <span>
              <Trash size={20} />
            </span>
            <div>
              <strong>清理演示数据</strong>
              <p>只删除已标记的演示租户数据。</p>
            </div>
            <button
              className="is-danger"
              onClick={() => {
                setOperation("cleanup");
                setConfirmation("");
              }}
              type="button"
            >
              清理数据
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
              {operation === "restore" ? "确认恢复数据库" : "确认清理演示数据"}
            </h2>
            <p>此操作不会在浏览器中直接执行；确认后只创建受审计的后端任务。</p>
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
                aria-label={operation === "restore" ? "取消恢复" : "取消清理"}
                onClick={() => setOperation(null)}
                type="button"
              >
                取消
              </button>
              <button
                className="is-danger"
                disabled={confirmation !== phrase}
                onClick={() => {
                  setStatus(
                    operation === "restore"
                      ? "恢复任务已安全入队 · 等待双人复核"
                      : "演示数据清理任务已安全入队 · 等待双人复核",
                  );
                  setOperation(null);
                }}
                type="button"
              >
                {operation === "restore" ? "确认恢复" : "确认清理"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

export function AuditPage() {
  return (
    <div className="admin-page">
      <AdminPageHeading description="检索认证、审核、Agent 与高风险数据操作" title="系统审计" />
      <section className="admin-panel admin-table-panel">
        <div className="admin-table-toolbar">
          <strong>不可变审计记录</strong>
          <span>按 event_id 追溯</span>
        </div>
        <table aria-label="系统审计记录" className="admin-data-table">
          <thead>
            <tr>
              <th>事件</th>
              <th>操作者</th>
              <th>对象</th>
              <th>结果</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">AUD-8810</th>
              <td>admin@pymentor</td>
              <td>REG-2801</td>
              <td>REGISTRATION_APPROVED</td>
              <td>12:04</td>
            </tr>
            <tr>
              <th scope="row">AUD-8809</th>
              <td>resource-worker</td>
              <td>RES-102</td>
              <td>REVIEW_REQUIRED</td>
              <td>11:58</td>
            </tr>
            <tr>
              <th scope="row">AUD-8808</th>
              <td>system</td>
              <td>backup-0717</td>
              <td>BACKUP_VERIFIED</td>
              <td>03:16</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  );
}
