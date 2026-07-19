import {
  ArrowRight,
  BookOpenText,
  CalendarBlank,
  ChartBar,
  ChatCircleDots,
  CheckCircle,
  Clock,
  Lock,
  MapTrifold,
  Pause,
  Sparkle,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import {
  getCurrentPathApiV1PathsCurrentGet,
  getDueReviewsApiV1ReviewsDueGet,
  getMasteryApiV1MasteryGet,
  getTodayApiV1LearningTodayGet,
  startTaskApiV1TasksTaskVersionIdStartPost,
  type MasteryView,
  type ReviewView,
} from "@pymentor/api-client";
import { StatePanel } from "@pymentor/ui";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  commandHeaders,
  configureStudentApi,
  safeApiMessage,
  studentAuthorization,
} from "../../student-api";
import { useAuth } from "../auth/auth-session";

const USING_TEST_FIXTURES = import.meta.env.MODE === "test";

type LearningTaskCard = {
  action: string;
  duration: string;
  evidence: string;
  eyebrow: string;
  id: string;
  priority: number;
  reason: string;
  taskVersionId?: string;
  title: string;
  tone: string;
};

const fixtureTaskDtos: LearningTaskCard[] = [
  {
    action: "开始复测",
    duration: "15 分钟",
    evidence: "EVD-1882",
    eyebrow: "DUE REVIEW · 今天到期",
    id: "review-loop-boundary",
    priority: 1,
    reason: "你在最近两次循环边界测试中出现同类错误，需要用新场景确认稳定掌握。",
    title: "到期复测：循环边界",
    tone: "review",
  },
  {
    action: "继续学习",
    duration: "35 分钟",
    evidence: "PATH-NODE-24",
    eyebrow: "CORE TASK · 推荐路径",
    id: "function-parameters",
    priority: 2,
    reason: "函数参数是下一节点“列表处理”的前置知识，路径验证器已确认依赖完整。",
    title: "函数参数与返回值",
    tone: "core",
  },
  {
    action: "查看讲解",
    duration: "20 分钟",
    evidence: "PROFILE-v3",
    eyebrow: "SUPPORT · 能力补强",
    id: "debug-trace",
    priority: 3,
    reason: "画像显示“调试与错误定位”仍需补强，先看执行轨迹再进入代码练习。",
    title: "从 Trace 定位 IndexError",
    tone: "support",
  },
];

export function TodayPage() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [completedTasks, setCompletedTasks] = useState<string[]>(
    USING_TEST_FIXTURES ? ["warmup"] : [],
  );
  const [planMessage, setPlanMessage] = useState<string | null>(null);
  const [rescheduleOpen, setRescheduleOpen] = useState(false);
  const [newTime, setNewTime] = useState("tomorrow-evening");
  const [tasks, setTasks] = useState<LearningTaskCard[] | null>(
    USING_TEST_FIXTURES ? fixtureTaskDtos : null,
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const view = searchParams.get("view");

  useEffect(() => {
    if (USING_TEST_FIXTURES) return;
    const accessToken = session?.accessToken;
    if (!accessToken) {
      setLoadError("登录会话缺少访问令牌，请重新登录");
      return;
    }
    let active = true;
    configureStudentApi();
    void getTodayApiV1LearningTodayGet({
      headers: studentAuthorization(accessToken),
    })
      .then((result) => {
        if (!active) return;
        if (!result.data) throw new Error(safeApiMessage(result.error));
        setTasks(
          result.data.map((item, index) => ({
            action: item.kind === "REVIEW" ? "开始复测" : "开始任务",
            duration: `${item.estimated_minutes} 分钟`,
            evidence: item.task_version_id ?? item.id,
            eyebrow: `${item.kind} · ${item.due_at ? "已安排到期时间" : "服务端学习路径"}`,
            id: item.id,
            priority: index + 1,
            reason: `节点 ${item.node_id}，由服务端路径与任务编译器发布。`,
            taskVersionId: item.task_version_id ?? undefined,
            title:
              item.kind === "REVIEW"
                ? `到期复测 · ${item.node_id.slice(0, 8)}`
                : `学习任务 · ${item.node_id.slice(0, 8)}`,
            tone: item.kind === "REVIEW" ? "review" : "core",
          })),
        );
      })
      .catch((error: unknown) => {
        if (active) setLoadError(safeApiMessage(error));
      });
    return () => {
      active = false;
    };
  }, [session?.accessToken]);

  if (view === "loading") {
    return (
      <StatePanel
        description="正在同步你的学习计划与资源进度"
        state="loading"
        title="加载今日任务"
      />
    );
  }
  if (view === "empty") {
    return (
      <StatePanel
        actionLabel="查看学习地图"
        description="完成画像诊断后，我们会为你安排第一项学习任务"
        onAction={() => undefined}
        state="empty"
        title="今天还没有学习任务"
      />
    );
  }
  if (view === "error") {
    return (
      <StatePanel
        actionLabel="重试"
        description="任务暂时没有加载成功，已保留你本地的学习进度"
        onAction={() => window.location.reload()}
        state="error"
        title="无法加载今日任务"
      />
    );
  }
  if (view === "offline") {
    return (
      <StatePanel
        actionLabel="重新连接"
        description="你仍可查看已缓存内容；联网后会自动同步正式进度"
        onAction={() => window.location.reload()}
        state="offline"
        title="当前处于离线状态"
      />
    );
  }
  if (view === "delayed") {
    return (
      <StatePanel
        actionLabel="使用可用资源继续"
        description="图解与音频仍在生成；可先使用文本讲解与代码例题，完成后会自动补齐"
        onAction={() => undefined}
        state="loading"
        title="资源仍在生成"
      />
    );
  }
  if (view === "permission") {
    return (
      <StatePanel
        actionLabel="返回今日计划"
        description="课程权限可能已变更，已停止显示缓存的任务内容"
        onAction={() => undefined}
        state="error"
        title="无权访问此任务"
      />
    );
  }

  if (!USING_TEST_FIXTURES && loadError) {
    return (
      <StatePanel
        actionLabel="重试"
        description={loadError}
        onAction={() => window.location.reload()}
        state="error"
        title="无法加载今日任务"
      />
    );
  }
  if (!tasks) {
    return <StatePanel description="正在读取服务端学习计划" state="loading" title="加载今日任务" />;
  }
  if (tasks.length === 0) {
    return (
      <StatePanel
        actionLabel="查看学习地图"
        description="当前没有已发布任务；完成画像或等待路径编译后再试"
        onAction={() => navigate("/map")}
        state="empty"
        title="今天还没有学习任务"
      />
    );
  }

  const completion = Math.round((completedTasks.length / Math.max(tasks.length, 1)) * 100);
  const estimatedMinutes = tasks.reduce((total, task) => {
    const minutes = Number.parseInt(task.duration, 10);
    return total + (Number.isFinite(minutes) ? minutes : 0);
  }, 0);
  const dueReviews = tasks.filter((task) => task.tone === "review").length;

  return (
    <div className="foundation-page today-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">TODAY · 个性化学习</p>
          <h1>今日学习工作台</h1>
          <p>优先完成到期复测，再按已验证路径推进新知识</p>
        </div>
        <div aria-label="今日计划操作" className="today-heading-actions" role="group">
          <Link className="profile-secondary-button today-heading-action" to="/resources">
            <BookOpenText size={16} /> 学习资源
          </Link>
          <Link className="profile-secondary-button today-heading-action" to="/tutor">
            <ChatCircleDots size={16} /> 智能辅导
          </Link>
          <button
            onClick={() => setPlanMessage("今日计划已暂停，正式任务状态保持不变")}
            type="button"
          >
            <Pause size={16} /> 暂停今日计划
          </button>
          <button onClick={() => setRescheduleOpen(true)} type="button">
            <CalendarBlank size={16} /> 重新安排任务
          </button>
        </div>
      </div>

      {planMessage ? (
        <p aria-label="计划状态" className="today-plan-message" role="status">
          {planMessage}
        </p>
      ) : null}

      <section aria-label="今日进度" className="today-overview">
        <div>
          <span>今日完成</span>
          <strong>
            {completedTasks.length}/{tasks.length}
          </strong>
        </div>
        <div>
          <span>预计用时</span>
          <strong>{estimatedMinutes} 分钟</strong>
        </div>
        <div>
          <span>到期复测</span>
          <strong>{dueReviews} 项</strong>
        </div>
        <div className="today-progress">
          <span>任务完成度</span>
          <progress
            aria-label="今日任务完成度"
            aria-valuemax={100}
            aria-valuemin={0}
            aria-valuenow={completion}
            max={100}
            value={completion}
          />
          <strong>{completion}%</strong>
        </div>
      </section>

      <section aria-labelledby="today-task-list-title" className="today-task-section">
        <div className="section-heading-row">
          <div>
            <p className="eyebrow">RECOMMENDED ORDER</p>
            <h2 id="today-task-list-title">今天的任务</h2>
          </div>
          <span>顺序由服务端任务编译器给出</span>
        </div>
        <div className="today-task-list">
          {tasks.map((task) => {
            const complete = completedTasks.includes(task.id);
            return (
              <article
                aria-label={task.title}
                className={`learning-task learning-task--${task.tone}`}
                data-priority={task.priority}
                key={task.id}
              >
                <div className="learning-task__order">
                  {complete ? <CheckCircle size={24} weight="fill" /> : task.priority}
                </div>
                <div className="learning-task__content">
                  <p className="eyebrow">{task.eyebrow}</p>
                  <h3>{task.title}</h3>
                  <p>{task.reason}</p>
                  <div className="learning-task__meta">
                    <span>
                      <Clock size={15} /> {task.duration}
                    </span>
                    <span>依据 {task.evidence}</span>
                  </div>
                </div>
                <button
                  className={task.priority === 1 ? "py-button" : "profile-secondary-button"}
                  disabled={complete}
                  onClick={async () => {
                    if (USING_TEST_FIXTURES) {
                      setCompletedTasks((current) => [...new Set([...current, task.id])]);
                      return;
                    }
                    const accessToken = session?.accessToken;
                    if (!accessToken || !task.taskVersionId) {
                      setPlanMessage("该步骤尚未发布可执行任务版本");
                      return;
                    }
                    configureStudentApi();
                    const result = await startTaskApiV1TasksTaskVersionIdStartPost({
                      headers: commandHeaders(accessToken, "web-task-start"),
                      path: { task_version_id: task.taskVersionId },
                    });
                    if (!result.data) {
                      setPlanMessage(safeApiMessage(result.error));
                      return;
                    }
                    navigate(
                      `/lab?task_instance_id=${result.data.id}&version=${result.data.version}`,
                    );
                  }}
                  type="button"
                >
                  {complete ? "已完成" : task.action} {complete ? null : <ArrowRight size={16} />}
                </button>
              </article>
            );
          })}
        </div>
      </section>

      {rescheduleOpen ? (
        <div className="dialog-backdrop">
          <section
            aria-labelledby="reschedule-title"
            aria-modal="true"
            className="profile-dialog"
            role="dialog"
          >
            <button
              aria-label="关闭重新安排对话框"
              className="profile-dialog__close"
              onClick={() => setRescheduleOpen(false)}
              type="button"
            >
              <X size={18} />
            </button>
            <p className="eyebrow">RESCHEDULE</p>
            <h2 id="reschedule-title">重新安排学习任务</h2>
            <p>只调整计划时间，不在浏览器中修改掌握状态或复测结论。</p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                setPlanMessage(
                  newTime === "tomorrow-evening" ? "已安排到明天 19:30" : "已安排到周六 09:00",
                );
                setRescheduleOpen(false);
              }}
            >
              <label htmlFor="reschedule-time">新的学习时间</label>
              <select
                id="reschedule-time"
                onChange={(event) => setNewTime(event.target.value)}
                value={newTime}
              >
                <option value="tomorrow-evening">明天 19:30</option>
                <option value="saturday-morning">周六 09:00</option>
              </select>
              <div>
                <button
                  className="profile-secondary-button"
                  onClick={() => setRescheduleOpen(false)}
                  type="button"
                >
                  取消
                </button>
                <button className="py-button" type="submit">
                  确认重新安排
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
    </div>
  );
}

type PathNodeRow = readonly [string, string, string, string];

const fixturePathNodes: PathNodeRow[] = [
  ["01", "变量与表达式", "STABLE_MASTERY · 稳定掌握", "已通过到期复测"],
  ["02", "条件与循环", "STABLE_MASTERY · 稳定掌握", "最近复测 92 分"],
  ["03", "函数基础", "LEARNING · 学习中", "当前路径节点"],
  ["04", "函数参数与返回值", "UNSEEN · 未开始", "前置：函数基础"],
  ["05", "列表与字典", "LOCKED · 待解锁", "等待路径前置完成"],
];

export function LearningMapPage() {
  const { session } = useAuth();
  const [searchParams] = useSearchParams();
  const [pathNodes, setPathNodes] = useState<PathNodeRow[] | null>(
    USING_TEST_FIXTURES ? fixturePathNodes : null,
  );
  const [pathVersion, setPathVersion] = useState<number | null>(USING_TEST_FIXTURES ? 7 : null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (USING_TEST_FIXTURES) return;
    const accessToken = session?.accessToken;
    if (!accessToken) {
      setLoadError("登录会话缺少访问令牌，请重新登录");
      return;
    }
    let active = true;
    configureStudentApi();
    void Promise.all([
      getCurrentPathApiV1PathsCurrentGet({ headers: studentAuthorization(accessToken) }),
      getMasteryApiV1MasteryGet({ headers: studentAuthorization(accessToken) }),
    ])
      .then(([pathResult, masteryResult]) => {
        if (!active) return;
        if (!pathResult.data) throw new Error(safeApiMessage(pathResult.error));
        if (!masteryResult.data) throw new Error(safeApiMessage(masteryResult.error));
        const masteryByNode = new Map(
          masteryResult.data.map((item) => [item.node_id, item.status]),
        );
        setPathVersion(pathResult.data.version);
        setPathNodes(
          pathResult.data.steps.map((step) => {
            const mastery = masteryByNode.get(step.node_id);
            const status = mastery
              ? `${mastery} · 服务端掌握状态`
              : step.position === 1
                ? "LEARNING · 学习中"
                : "UNSEEN · 未开始";
            return [
              String(step.position).padStart(2, "0"),
              `节点 ${step.node_id.slice(0, 8)}`,
              status,
              `${step.kind} · ${step.scenario_key} · ${step.validation_status}`,
            ] as const;
          }),
        );
      })
      .catch((error: unknown) => {
        if (active) setLoadError(safeApiMessage(error));
      });
    return () => {
      active = false;
    };
  }, [session?.accessToken]);

  if (searchParams.get("view") === "permission") {
    return (
      <StatePanel
        description="你已不在该课程中，路径数据已停止展示"
        state="error"
        title="无权查看学习路径"
      />
    );
  }
  if (!USING_TEST_FIXTURES && loadError) {
    return (
      <StatePanel
        actionLabel="重试"
        description={loadError}
        onAction={() => window.location.reload()}
        state="error"
        title="无法加载学习路径"
      />
    );
  }
  if (!pathNodes) {
    return (
      <StatePanel description="正在读取服务端已验证路径" state="loading" title="加载学习地图" />
    );
  }

  return (
    <div className="foundation-page map-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">LEARNING MAP · VALIDATED PATH</p>
          <h1>学习地图</h1>
          <p>路径建议经确定性验证器补齐前置关系后发布</p>
        </div>
        <span className="status-chip">
          <MapTrifold size={16} /> Path v{pathVersion ?? "-"}
        </span>
      </div>
      <div aria-label="学习路径已调整" className="path-change-banner" role="status">
        <Sparkle size={22} weight="fill" />
        <div>
          <strong>{USING_TEST_FIXTURES ? "学习路径已调整" : "服务端路径已验证"}</strong>
          <p>
            {USING_TEST_FIXTURES
              ? "依据最近两次边界测试，已在函数参数前插入“函数基础”巩固节点。"
              : "当前顺序、场景和修复状态均来自持久化路径版本。"}
          </p>
        </div>
        <span>规则验证通过</span>
      </div>
      <div className="map-layout">
        <section aria-labelledby="current-path-title" className="map-path-panel">
          <div className="section-heading-row">
            <div>
              <p className="eyebrow">CURRENT PATH</p>
              <h2 id="current-path-title">当前学习路径</h2>
            </div>
            <small>5 个节点 · 2 个稳定掌握</small>
          </div>
          <ol aria-label="当前学习路径" className="path-node-list">
            {pathNodes.map(([index, title, status, note]) => (
              <li className={status.startsWith("LEARNING") ? "is-current" : ""} key={index}>
                <span className="path-node-index">{index}</span>
                <div>
                  <strong>{title}</strong>
                  <small>{note}</small>
                </div>
                <span className="path-node-status">{status}</span>
              </li>
            ))}
          </ol>
        </section>
        <aside className="map-reason-panel">
          <p className="eyebrow">WHY THIS PATH</p>
          <h2>为什么这样安排？</h2>
          <p>你能写出循环，但两次在边界值上出错。规则组件保留已稳定掌握节点，仅补强函数前置。</p>
          <dl>
            <div>
              <dt>证据</dt>
              <dd>EVD-1882 / EVD-1901</dd>
            </div>
            <div>
              <dt>路径候选</dt>
              <dd>path-candidate-08</dd>
            </div>
            <div>
              <dt>验证结果</dt>
              <dd>VALID · 自动插入前置</dd>
            </div>
          </dl>
          <Link className="profile-secondary-button" to="/growth/profile">
            查看相关画像证据
          </Link>
        </aside>
      </div>
    </div>
  );
}

export function GrowthPage() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [reviewRequested, setReviewRequested] = useState(false);
  const [mastery, setMastery] = useState<MasteryView[] | null>(USING_TEST_FIXTURES ? [] : null);
  const [dueReviews, setDueReviews] = useState<ReviewView[] | null>(
    USING_TEST_FIXTURES ? [] : null,
  );
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (USING_TEST_FIXTURES) return;
    const accessToken = session?.accessToken;
    if (!accessToken) {
      setLoadError("登录会话缺少访问令牌，请重新登录");
      return;
    }
    let active = true;
    configureStudentApi();
    void Promise.all([
      getMasteryApiV1MasteryGet({ headers: studentAuthorization(accessToken) }),
      getDueReviewsApiV1ReviewsDueGet({ headers: studentAuthorization(accessToken) }),
    ])
      .then(([masteryResult, reviewResult]) => {
        if (!active) return;
        if (!masteryResult.data) throw new Error(safeApiMessage(masteryResult.error));
        if (!reviewResult.data) throw new Error(safeApiMessage(reviewResult.error));
        setMastery(masteryResult.data);
        setDueReviews(reviewResult.data);
      })
      .catch((error: unknown) => {
        if (active) setLoadError(safeApiMessage(error));
      });
    return () => {
      active = false;
    };
  }, [session?.accessToken]);

  if (!USING_TEST_FIXTURES && loadError) {
    return (
      <StatePanel
        actionLabel="重试"
        description={loadError}
        onAction={() => window.location.reload()}
        state="error"
        title="无法加载成长记录"
      />
    );
  }
  if (!mastery || !dueReviews) {
    return (
      <StatePanel description="正在读取服务端掌握与复测记录" state="loading" title="加载成长记录" />
    );
  }

  const masteryCount = (status: MasteryView["status"]) =>
    mastery.filter((item) => item.status === status).length;
  const metrics = USING_TEST_FIXTURES
    ? [
        ["稳定掌握", "12", "+2 本周"],
        ["初步掌握", "5", "等待复测"],
        ["学习中", "3", "当前路径"],
        ["到期复测", "1", "今天"],
      ]
    : [
        ["稳定掌握", String(masteryCount("STABLE_MASTERY")), "正式状态"],
        ["初步掌握", String(masteryCount("INITIAL_MASTERY")), "等待复测"],
        ["学习中", String(masteryCount("LEARNING")), "正式状态"],
        ["到期复测", String(dueReviews.length), "服务端计划"],
      ];
  const firstReview = dueReviews[0];

  return (
    <div className="foundation-page growth-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">GROWTH · REVIEW LOOP</p>
          <h1>我的成长</h1>
          <p>查看掌握状态、证据变化与到期复测，不把单次通过等同于真正掌握</p>
        </div>
        <Link className="profile-secondary-button growth-profile-link" to="/growth/profile">
          <ChartBar size={16} /> 查看八维画像
        </Link>
      </div>
      <section aria-label="成长概览" className="growth-metrics">
        {metrics.map(([label, value, note]) => (
          <article key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
            <small>{note}</small>
          </article>
        ))}
      </section>
      <div className="growth-layout">
        <section className="growth-timeline" aria-labelledby="growth-timeline-title">
          <div className="section-heading-row">
            <div>
              <p className="eyebrow">MASTERY TIMELINE</p>
              <h2 id="growth-timeline-title">最近掌握变化</h2>
            </div>
            <span>初步掌握 ≠ 稳定掌握</span>
          </div>
          <ol>
            {(USING_TEST_FIXTURES
              ? [
                  ["条件分支进入稳定掌握", "2026-07-16 · 到期复测通过 · EVD-1844", "stable"],
                  ["循环边界保持初步掌握", "2026-07-15 · 等待新场景复测 · EVD-1882", "initial"],
                  ["函数基础开始学习", "2026-07-14 · 路径 v7 发布", "learning"],
                ]
              : mastery
                  .slice(0, 8)
                  .map((item) => [
                    `节点 ${item.node_id.slice(0, 8)} · ${item.status}`,
                    `正式状态版本 ${item.version}${item.review_due_at ? ` · 复测 ${item.review_due_at}` : ""}`,
                    item.status,
                  ])
            ).map(([title, detail, state]) => (
              <li key={`${title}-${detail}`}>
                <span>
                  {state === "stable" || state === "STABLE_MASTERY" ? (
                    <CheckCircle size={18} weight="fill" />
                  ) : state === "initial" || state === "INITIAL_MASTERY" ? (
                    <WarningCircle size={18} />
                  ) : (
                    <Sparkle size={18} />
                  )}
                </span>
                <div>
                  <strong>{title}</strong>
                  <p>{detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>
        <aside className="due-review-card">
          <span className="due-review-card__icon">
            <Clock size={22} />
          </span>
          <p className="eyebrow">DUE REVIEW</p>
          <h2>
            {USING_TEST_FIXTURES
              ? "循环边界复测"
              : firstReview
                ? `节点 ${firstReview.node_id.slice(0, 8)} 复测`
                : "当前没有到期复测"}
          </h2>
          <p>
            {USING_TEST_FIXTURES
              ? "使用未见过的列表场景，确认你是否能稳定处理 off-by-one。"
              : firstReview
                ? `场景 ${firstReview.scenario_key}，结论将由服务端证据规则决定。`
                : "新的复测将由服务端计划在到期后显示。"}
          </p>
          <dl>
            <div>
              <dt>到期</dt>
              <dd>{USING_TEST_FIXTURES ? "今天 23:59" : (firstReview?.due_at ?? "—")}</dd>
            </div>
            <div>
              <dt>预计</dt>
              <dd>15 分钟</dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>{USING_TEST_FIXTURES ? "INITIAL_MASTERY" : (firstReview?.status ?? "NONE")}</dd>
            </div>
          </dl>
          <button
            className="py-button"
            disabled={!USING_TEST_FIXTURES && !firstReview}
            onClick={() => {
              if (USING_TEST_FIXTURES) setReviewRequested(true);
              else navigate("/today");
            }}
            type="button"
          >
            {USING_TEST_FIXTURES ? "申请循环边界复测" : "前往到期复测"} <ArrowRight size={16} />
          </button>
          {reviewRequested ? (
            <p aria-label="复测申请状态" className="profile-dispute-status" role="status">
              复测申请已提交 · 等待服务端生成新场景
            </p>
          ) : null}
        </aside>
      </div>
      <p className="growth-authority-note">
        <Lock size={15} /> 掌握状态由证据与规则引擎写入；本页面只展示服务端结论。
      </p>
    </div>
  );
}
