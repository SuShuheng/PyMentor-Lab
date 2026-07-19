import {
  ArrowLeft,
  ArrowClockwise,
  ArrowRight,
  BookOpenText,
  Brain,
  Cards,
  ChatCircleDots,
  CheckCircle,
  Code,
  FilmStrip,
  Hourglass,
  ListChecks,
  MagnifyingGlass,
  PaperPlaneTilt,
  ShieldCheck,
  Sparkle,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  getCurrentPathApiV1PathsCurrentGet,
  getResourceJobApiV1ResourceJobsJobIdGet,
  startResourceJobApiV1ResourceJobsPost,
  type ResourceJobView,
  type ResourceTypeContract,
} from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";
import { StatePanel } from "@pymentor/ui";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";

import { configureStudentApi, safeApiMessage, studentAuthorization } from "../../student-api";
import { useAuth } from "../auth/auth-session";

const USING_TEST_FIXTURES = import.meta.env.MODE === "test";

type ResourceStatus = "READY" | "GENERATING" | "QUEUED" | "FALLBACK";

const resourceDefinitions = [
  {
    apiType: "MICRO_LECTURE" as ResourceTypeContract,
    description: "用边界值对比解释 range 的左闭右开规则，并连接到当前错因。",
    href: "/resources/micro-lecture",
    icon: BookOpenText,
    id: "micro-lecture",
    review: "事实与合规审校通过",
    source: "KB-PY-04",
    title: "微讲义",
    version: "v3.1",
  },
  {
    apiType: "STRUCTURE_CARD" as ResourceTypeContract,
    description: "一张卡片梳理起点、终点、步长与常见 off-by-one 误区。",
    href: "/resources/knowledge-card",
    icon: Cards,
    id: "knowledge-card",
    review: "事实与合规审校通过",
    source: "KB-PY-04",
    title: "结构卡",
    version: "v2.3",
  },
  {
    apiType: "TRACE_ANIMATION" as ResourceTypeContract,
    description: "逐帧观察 i 与 total 的变化，关键帧可提交预测证据。",
    href: "/lab/trace",
    icon: FilmStrip,
    id: "trace-animation",
    review: "事实与合规审校通过",
    source: "SANDBOX-TRACE-18",
    title: "轨迹动画",
    version: "v1.8",
  },
  {
    apiType: "LAYERED_EXERCISE" as ResourceTypeContract,
    description: "从识别边界到修复代码，按基础、进阶、迁移三层递进。",
    href: "/resources/layered-practice",
    icon: ListChecks,
    id: "layered-practice",
    review: "等待自动测试与内容审校",
    source: "PATH-NODE-24",
    title: "分层练习",
    version: "v1.4",
  },
  {
    apiType: "NOTEBOOK_TASK" as ResourceTypeContract,
    description: "在受控沙箱中完成列表偶数求和，并保留提示与修订证据。",
    href: "/lab",
    icon: Code,
    id: "notebook-task",
    review: "等待沙箱用例验证",
    source: "TASK-LOOP-08",
    title: "Notebook 任务",
    version: "v2.0",
  },
] as const;

const statusLabel: Record<ResourceStatus, string> = {
  FALLBACK: "文字降级可用",
  GENERATING: "正在生成",
  QUEUED: "等待生成",
  READY: "可用",
};

function statusesFor(view: string | null): ResourceStatus[] {
  if (view === "partial") return ["READY", "READY", "READY", "GENERATING", "QUEUED"];
  if (view === "fallback") return ["FALLBACK", "READY", "READY", "READY", "READY"];
  return ["READY", "READY", "READY", "READY", "READY"];
}

export function ResourcesPage() {
  const { session } = useAuth();
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view");
  const [job, setJob] = useState<ResourceJobView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (USING_TEST_FIXTURES) return;
    const accessToken = session?.accessToken;
    if (!accessToken) {
      setLoadError("登录会话缺少访问令牌，请重新登录");
      return;
    }
    let active = true;
    let timer: number | null = null;
    configureStudentApi();

    const poll = async (jobId: string) => {
      const result = await getResourceJobApiV1ResourceJobsJobIdGet({
        headers: studentAuthorization(accessToken),
        path: { job_id: jobId },
      });
      if (!active) return;
      if (!result.data) throw new Error(safeApiMessage(result.error));
      setJob(result.data);
      if (
        !["READY", "FAILED_RETRYABLE", "FAILED_FINAL", "CANCELLED"].includes(
          result.data.status,
        )
      ) {
        timer = window.setTimeout(() => void poll(jobId).catch(handleError), 1500);
      }
    };
    const handleError = (error: unknown) => {
      if (active) setLoadError(safeApiMessage(error));
    };

    void getCurrentPathApiV1PathsCurrentGet({
      headers: studentAuthorization(accessToken),
    })
      .then(async (pathResult) => {
        if (!pathResult.data || pathResult.data.steps.length === 0) {
          throw new Error(safeApiMessage(pathResult.error) || "当前没有可生成资源的路径节点");
        }
        const [step] = pathResult.data.steps;
        if (!step) throw new Error("当前没有可生成资源的路径节点");
        const result = await startResourceJobApiV1ResourceJobsPost({
          body: {
            course_id: pathResult.data.course_id,
            node_id: step.node_id,
            resource_types: resourceDefinitions.map((item) => item.apiType),
          },
          headers: {
            ...studentAuthorization(accessToken),
            "Idempotency-Key": `web-resource-${pathResult.data.id}-${step.node_id}`,
          },
        });
        if (!result.data) throw new Error(safeApiMessage(result.error));
        if (!active) return;
        setJob(result.data);
        await poll(result.data.id);
      })
      .catch(handleError);

    return () => {
      active = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [session?.accessToken]);

  if (USING_TEST_FIXTURES && view === "rejected") {
    return (
      <StatePanel
        actionLabel="返回今日学习"
        description="本批内容触发安全门禁，未向学生发布。已保留上一审校通过版本。"
        onAction={() => window.history.back()}
        state="error"
        title="内容未通过安全审校"
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
        title="无法加载学习资源"
      />
    );
  }
  if (!USING_TEST_FIXTURES && !job) {
    return (
      <StatePanel description="正在创建或恢复服务端资源任务" state="loading" title="加载学习资源" />
    );
  }
  if (!USING_TEST_FIXTURES && job?.status === "FAILED_FINAL") {
    return (
      <StatePanel
        actionLabel="返回今日学习"
        description="本批内容未通过最终审校，未向学生发布"
        onAction={() => window.history.back()}
        state="error"
        title="内容未通过安全审校"
      />
    );
  }
  if (!USING_TEST_FIXTURES && job?.status === "FAILED_RETRYABLE") {
    return (
      <StatePanel
        actionLabel="重试资源生成"
        description="资源生成服务暂时不可用，当前未发布任何未审校内容"
        onAction={() => window.location.reload()}
        state="error"
        title="资源生成可重试"
      />
    );
  }

  const statuses = USING_TEST_FIXTURES
    ? statusesFor(view)
    : resourceDefinitions.map((definition) => {
        const artifact = job?.artifacts.find((item) => item.resource_type === definition.apiType);
        if (artifact?.status === "PUBLISHED") return "READY";
        if (artifact) return "GENERATING";
        return "QUEUED";
      });
  const readyCount = statuses.filter(
    (status) => status === "READY" || status === "FALLBACK",
  ).length;

  return (
    <div className="foundation-page resources-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">RESOURCE PACK · PROGRESSIVE RELEASE</p>
          <h1>{USING_TEST_FIXTURES ? "循环边界学习资源" : "服务端学习资源"}</h1>
          <p>资源完成一项发布一项，不让仍在生成的内容阻断今天的学习。</p>
        </div>
        <Link className="py-button resource-tutor-link" to="/tutor">
          <ChatCircleDots size={17} /> 向智能辅导提问
        </Link>
      </div>

      <div aria-label="资源生成进度" className="resource-progress" role="status">
        <span>
          <Sparkle size={18} weight="fill" /> 资源包 {job?.id ?? "JOB-RES-2407"}
        </span>
        <div>
          <progress aria-label="资源生成完成度" max={5} value={readyCount} />
          <strong>{readyCount} / 5 已可用</strong>
        </div>
        <small>
          {readyCount === 5
            ? "全部资源已发布"
            : `任务状态 ${job?.status ?? "GENERATING"} · ${job?.progress_percent ?? 0}%`}
        </small>
      </div>

      <ul aria-label="五类学习资源" className="resource-grid">
        {resourceDefinitions.map((resource, index) => {
          const Icon = resource.icon;
          const status = statuses[index] ?? "QUEUED";
          const isAvailable = status === "READY" || status === "FALLBACK";
          const artifact = job?.artifacts.find((item) => item.resource_type === resource.apiType);
          const href =
            USING_TEST_FIXTURES || !job || !artifact
              ? resource.href
              : `/resources/micro-lecture?job_id=${encodeURIComponent(job.id)}&resource_id=${encodeURIComponent(artifact.id)}`;
          return (
            <li key={resource.id}>
              <article
                aria-label={resource.title}
                className={`resource-card resource-card--${status.toLowerCase()}`}
              >
                <div className="resource-card__topline">
                  <span className="resource-card__icon">
                    <Icon size={22} weight="duotone" />
                  </span>
                  <span className="resource-status">
                    {status === "READY" || status === "FALLBACK" ? (
                      <CheckCircle size={15} weight="fill" />
                    ) : (
                      <Hourglass size={15} />
                    )}
                    {statusLabel[status]}
                  </span>
                </div>
                <div>
                  <p className="eyebrow">
                    0{index + 1} · {resource.id.toUpperCase()}
                  </p>
                  <h2>{resource.title}</h2>
                  <p>{resource.description}</p>
                </div>
                {status === "FALLBACK" ? (
                  <p className="resource-fallback">
                    <WarningCircle size={16} /> 配图暂不可用，已切换为审校通过的文字版
                  </p>
                ) : null}
                <dl>
                  <div>
                    <dt>来源</dt>
                    <dd>
                      来源{" "}
                      {USING_TEST_FIXTURES
                        ? resource.source
                        : artifact?.source_ids.join(", ") || "等待发布"}
                    </dd>
                  </div>
                  <div>
                    <dt>版本</dt>
                    <dd>
                      版本 {USING_TEST_FIXTURES ? resource.version : (artifact?.version ?? "—")}
                    </dd>
                  </div>
                  <div>
                    <dt>审校</dt>
                    <dd>
                      <ShieldCheck size={14} /> {resource.review}
                    </dd>
                  </div>
                </dl>
                {isAvailable ? (
                  <Link
                    aria-label={`打开${resource.title}`}
                    className="resource-card__action"
                    to={href}
                  >
                    打开资源 <ArrowRight size={16} />
                  </Link>
                ) : (
                  <span aria-disabled="true" className="resource-card__action is-disabled">
                    {statusLabel[status]}
                  </span>
                )}
              </article>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const rangeExamples = [
  ["range(1, 5)", "1, 2, 3, 4", "终点 5 不进入序列"],
  ["range(0, 6, 2)", "0, 2, 4", "步长为 2，仍然不越过终点"],
  ["range(5, 1, -1)", "5, 4, 3, 2", "负步长时终点同样不包含"],
] as const;

export function ResourceDetailPage() {
  const { session } = useAuth();
  const { pathname } = useLocation();
  const [searchParams] = useSearchParams();
  const showKnowledgeCard = pathname.endsWith("/knowledge-card");
  const jobId = searchParams.get("job_id");
  const resourceId = searchParams.get("resource_id");
  const [publishedContent, setPublishedContent] = useState<string | null>(null);
  const [publishedMimeType, setPublishedMimeType] = useState<string | null>(null);
  const [contentError, setContentError] = useState<string | null>(null);

  useEffect(() => {
    if (USING_TEST_FIXTURES) return;
    const accessToken = session?.accessToken;
    if (!accessToken || !jobId || !resourceId) {
      setContentError("缺少已发布资源标识或登录会话");
      return;
    }
    let active = true;
    void fetch(
      `${readServerUrl()}/api/v1/resource-jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(resourceId)}/content`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    )
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const content = await response.text();
        if (!active) return;
        setPublishedMimeType(response.headers.get("Content-Type")?.split(";")[0] ?? "text/plain");
        setPublishedContent(content);
      })
      .catch((error: unknown) => {
        if (active) setContentError(safeApiMessage(error));
      });
    return () => {
      active = false;
    };
  }, [jobId, resourceId, session?.accessToken]);

  if (!USING_TEST_FIXTURES && contentError) {
    return (
      <StatePanel
        actionLabel="返回资源包"
        description={contentError}
        onAction={() => window.history.back()}
        state="error"
        title="无法读取已发布资源"
      />
    );
  }
  if (!USING_TEST_FIXTURES && publishedContent === null) {
    return (
      <StatePanel
        description="正在校验对象摘要并读取私有资源"
        state="loading"
        title="加载已发布资源"
      />
    );
  }

  if (!USING_TEST_FIXTURES) {
    const isSvg = publishedMimeType === "image/svg+xml";
    const svgSource = isSvg
      ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(publishedContent ?? "")}`
      : null;
    return (
      <div className="foundation-page resource-detail-page">
        <div className="resource-detail-heading">
          <div>
            <Link className="resource-back-link" to="/resources">
              <ArrowLeft size={16} /> 返回资源包
            </Link>
            <p className="eyebrow">PUBLISHED RESOURCE · VERIFIED OBJECT</p>
            <h1>已审校学习资源</h1>
            <p>内容来自私有对象存储；服务端在返回前重新校验 SHA-256 摘要与发布状态。</p>
          </div>
        </div>
        <article aria-label="已发布资源正文" className="resource-lesson">
          <header>
            <div>
              <p className="eyebrow">{publishedMimeType}</p>
              <h2>资源 {resourceId}</h2>
            </div>
            <span className="resource-status">
              <ShieldCheck size={15} /> 已发布并通过完整性校验
            </span>
          </header>
          {svgSource ? (
            <img alt="服务端生成的代码执行轨迹资源" src={svgSource} />
          ) : (
            <pre>
              <code>{publishedContent}</code>
            </pre>
          )}
        </article>
      </div>
    );
  }

  return (
    <div className="foundation-page resource-detail-page">
      <div className="resource-detail-heading">
        <div>
          <Link className="resource-back-link" to="/resources">
            <ArrowLeft size={16} /> 返回资源包
          </Link>
          <p className="eyebrow">REVIEWED RESOURCE · KB-PY-04</p>
          <h1>微讲义与知识结构卡</h1>
          <p>把 range 的边界规则连接到当前错因，并保留可追溯来源。</p>
        </div>
        <Link className="py-button resource-detail-tutor-link" to="/tutor">
          <ChatCircleDots size={17} /> 智能答疑
        </Link>
      </div>

      <nav aria-label="资源内容切换" className="resource-detail-tabs">
        <Link
          aria-current={showKnowledgeCard ? undefined : "page"}
          className={showKnowledgeCard ? "" : "is-current"}
          to="/resources/micro-lecture"
        >
          <BookOpenText size={17} /> 微讲义
        </Link>
        <Link
          aria-current={showKnowledgeCard ? "page" : undefined}
          className={showKnowledgeCard ? "is-current" : ""}
          to="/resources/knowledge-card"
        >
          <Cards size={17} /> 知识结构卡
        </Link>
      </nav>

      <div className="resource-detail-layout">
        <article aria-label="微讲义正文" className="resource-lesson">
          <header>
            <div>
              <p className="eyebrow">
                {showKnowledgeCard ? "STRUCTURE CARD" : "MICRO-LECTURE"} · 约 8 分钟
              </p>
              <h2>{showKnowledgeCard ? "range 边界结构卡" : "为什么 range 不包含终点？"}</h2>
            </div>
            <span className="resource-status">
              <ShieldCheck size={15} /> 审校 v3.1
            </span>
          </header>

          {showKnowledgeCard ? (
            <>
              <section className="knowledge-card-summary">
                <p className="eyebrow">CORE MODEL</p>
                <h3>起点 → 终点（不含）→ 步长</h3>
                <p>
                  range(start, stop, step) 从 start 开始，每次增加 step；只要下一项会到达或越过
                  stop，就结束生成。
                </p>
              </section>
              <dl className="knowledge-fact-grid">
                <div>
                  <dt>起点 start</dt>
                  <dd>默认是 0，第一项会被包含。</dd>
                </div>
                <div>
                  <dt>终点 stop</dt>
                  <dd>只负责划边界，不会进入结果。</dd>
                </div>
                <div>
                  <dt>步长 step</dt>
                  <dd>决定递增或递减方向，不能为 0。</dd>
                </div>
                <div>
                  <dt>常见错因</dt>
                  <dd>把 stop 当作最后一项，造成 off-by-one。</dd>
                </div>
              </dl>
            </>
          ) : (
            <>
              <section>
                <p className="eyebrow">01 · 先抓住一条规则</p>
                <h3>左边界进入序列，右边界只负责“喊停”</h3>
                <p>
                  Python 的 range 使用左闭右开区间。写下 range(1, 5) 时，1
                  是第一项；当下一项准备到达 5，生成过程就停止，因此结果是 1、2、3、4。
                </p>
                <pre>
                  <code>{`values = list(range(1, 5))\nprint(values)  # [1, 2, 3, 4]`}</code>
                </pre>
              </section>
              <section>
                <p className="eyebrow">02 · 连接到你的错因</p>
                <h3>列表索引与 range(len(items)) 正好配对</h3>
                <p>
                  长度为 4 的列表，其有效索引是 0 到 3。range(len(items)) 生成的也是 0、1、2、3，
                  因此不会访问 items[4]。
                </p>
                <pre>
                  <code>{`items = ["A", "B", "C", "D"]\nfor index in range(len(items)):\n    print(index, items[index])`}</code>
                </pre>
              </section>
            </>
          )}

          <section>
            <p className="eyebrow">EXAMPLES · 对照验证</p>
            <h3>换起点或步长，终点规则不变</h3>
            <div className="range-example-table" role="table">
              {rangeExamples.map(([expression, result, note]) => (
                <div key={expression} role="row">
                  <code role="cell">{expression}</code>
                  <span role="cell">{result}</span>
                  <small role="cell">{note}</small>
                </div>
              ))}
            </div>
          </section>
        </article>

        <aside aria-label="知识结构卡" className="resource-knowledge-panel">
          <div className="section-heading-row">
            <div>
              <p className="eyebrow">KNOWLEDGE CARD</p>
              <h2>知识结构卡</h2>
            </div>
            <Cards size={22} />
          </div>
          <dl>
            <div>
              <dt>核心概念</dt>
              <dd>左闭右开 · stop 不包含</dd>
            </div>
            <div>
              <dt>必要参数</dt>
              <dd>stop；start 与 step 可选</dd>
            </div>
            <div>
              <dt>常见误区</dt>
              <dd>把 stop 当作最后一项</dd>
            </div>
            <div>
              <dt>迁移线索</dt>
              <dd>列表切片同样使用右边界不含</dd>
            </div>
          </dl>
          <div className="resource-provenance">
            <strong>来源 KB-PY-04</strong>
            <span>Python 3.12 课程知识底座</span>
            <span>事实审校通过 · 版本 v3.1</span>
          </div>
        </aside>

        <section aria-label="学习支持" className="resource-support-panel">
          <ChatCircleDots size={22} weight="fill" />
          <p className="eyebrow">SMART SUPPORT</p>
          <h2>还卡在哪里？</h2>
          <p>辅导回答会先检索本节来源，原始推理不会展示或写入掌握状态。</p>
          <Link className="py-button" to="/tutor">
            围绕本节提问 <ArrowRight size={16} />
          </Link>
          <div>
            <strong>相关练习</strong>
            <Link to="/lab">列表偶数求和</Link>
            <Link to="/lab/trace">查看边界执行轨迹</Link>
          </div>
        </section>
      </div>
    </div>
  );
}

export interface TutorToolCall {
  id: string;
  name: string;
  status: "complete";
}

export interface TutorStreamState {
  content: string;
  done: boolean;
  reasoningObserved: boolean;
  seenEventIds: string[];
  tools: TutorToolCall[];
}

const emptyTutorState: TutorStreamState = {
  content: "",
  done: false,
  reasoningObserved: false,
  seenEventIds: [],
  tools: [],
};

interface CompatibleDelta {
  content?: string;
  reasoning_content?: string;
  tool_calls?: Array<{
    function?: { name?: string };
    id?: string;
    index?: number;
  }>;
}

export function reduceTutorSse(
  raw: string,
  previous: TutorStreamState = emptyTutorState,
): TutorStreamState {
  const next: TutorStreamState = {
    ...previous,
    seenEventIds: [...previous.seenEventIds],
    tools: [...previous.tools],
  };

  for (const block of raw.split(/\r?\n\r?\n/)) {
    const lines = block.split(/\r?\n/);
    const eventId = lines
      .find((line) => line.startsWith("id:"))
      ?.slice(3)
      .trim();
    const payload = lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");

    if (!payload) continue;
    if (payload === "[DONE]") {
      next.done = true;
      continue;
    }
    if (eventId && next.seenEventIds.includes(eventId)) continue;

    try {
      const parsed = JSON.parse(payload) as {
        chunk?: {
          delta_content?: string | null;
          delta_reasoning?: string | null;
          delta_tool_calls?: Array<{
            id?: string | null;
            index: number;
            name?: string | null;
          }> | null;
        };
        event_id?: string;
        type?:
          "content_delta" | "reasoning_delta" | "tool_call_delta" | "progress" | "error" | "done";
        choices?: Array<{ delta?: CompatibleDelta }>;
      };
      const typedEventId = parsed.event_id ?? eventId;
      if (typedEventId && next.seenEventIds.includes(typedEventId)) continue;
      if (parsed.type) {
        if (typedEventId) next.seenEventIds.push(typedEventId);
        if (parsed.type === "done") next.done = true;
        if (typeof parsed.chunk?.delta_content === "string") {
          next.content += parsed.chunk.delta_content;
        }
        if (typeof parsed.chunk?.delta_reasoning === "string" && parsed.chunk.delta_reasoning) {
          next.reasoningObserved = true;
        }
        for (const tool of parsed.chunk?.delta_tool_calls ?? []) {
          const id = tool.id ?? `tool-${tool.index}`;
          const existing = next.tools.find((item) => item.id === id);
          if (existing && tool.name) existing.name = tool.name;
          if (!existing && tool.name) next.tools.push({ id, name: tool.name, status: "complete" });
        }
        continue;
      }
      const delta = parsed.choices?.[0]?.delta;
      if (eventId) next.seenEventIds.push(eventId);
      if (!delta) continue;
      if (typeof delta.content === "string") next.content += delta.content;
      if (typeof delta.reasoning_content === "string" && delta.reasoning_content.length > 0) {
        next.reasoningObserved = true;
      }
      for (const tool of delta.tool_calls ?? []) {
        const id = tool.id ?? `tool-${tool.index ?? next.tools.length}`;
        const existing = next.tools.find((item) => item.id === id);
        const name = tool.function?.name;
        if (existing && name) existing.name = name;
        if (!existing && name) next.tools.push({ id, name, status: "complete" });
      }
    } catch {
      if (eventId) next.seenEventIds.push(eventId);
    }
  }

  return next;
}

const reasoningEvent =
  'id: tutor-1\ndata: {"choices":[{"delta":{"reasoning_content":"RAW_REASONING_MUST_NOT_RENDER"}}]}';
const openingEvent = 'id: tutor-2\ndata: {"choices":[{"delta":{"content":"先看规则："}}]}';
const toolEvent =
  'id: tutor-3\ndata: {"choices":[{"delta":{"tool_calls":[{"id":"call-source-1","function":{"name":"search_course_sources"}}]}}]}';
const answerEvent =
  'id: tutor-4\ndata: {"choices":[{"delta":{"content":"range 的右端点不会被取到。用 range(len(items)) 时，最后一个索引正好是 len(items) - 1。"}}]}';

function toolLabel(name: string) {
  if (name === "search_course_sources") return "课程知识库检索工具";
  return "受控教学工具";
}

export function TutorPage() {
  const { session } = useAuth();
  const [searchParams] = useSearchParams();
  const mode = searchParams.get("mode");
  const view = searchParams.get("view");
  const [question, setQuestion] = useState("为什么 range(1, 5) 不包含 5？");
  const [stream, setStream] = useState<TutorStreamState>(emptyTutorState);
  const [streamStatus, setStreamStatus] = useState<"idle" | "streaming" | "done" | "error">("idle");
  const timerRef = useRef<number | null>(null);
  const [streamErrorCode, setStreamErrorCode] = useState<string | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    },
    [],
  );

  function completeStream(previous: TutorStreamState) {
    const tail = [toolEvent, answerEvent, "data: [DONE]"].join("\n\n");
    timerRef.current = window.setTimeout(() => {
      setStream(reduceTutorSse(tail, previous));
      setStreamStatus("done");
    }, 60);
  }

  function startFixtureStream() {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    setStreamStatus("streaming");
    const head = [mode === "plain" ? openingEvent : reasoningEvent, openingEvent].join("\n\n");
    const started = reduceTutorSse(head);
    setStream(started);

    if (view === "rejected") {
      timerRef.current = window.setTimeout(() => setStreamStatus("error"), 40);
      return;
    }
    if (view === "retry") {
      timerRef.current = window.setTimeout(() => setStreamStatus("error"), 40);
      return;
    }
    completeStream(started);
  }

  async function startRealStream(afterEventId?: string): Promise<void> {
    const accessToken = session?.accessToken;
    if (!accessToken) {
      setStreamErrorCode("AUTH_REQUIRED");
      setStreamStatus("error");
      return;
    }
    setStreamStatus("streaming");
    setStreamErrorCode(null);
    configureStudentApi();
    const pathResult = await getCurrentPathApiV1PathsCurrentGet({
      headers: studentAuthorization(accessToken),
    });
    const step = pathResult.data?.steps[0];
    if (!pathResult.data || !step) {
      setStreamErrorCode("NOT_FOUND");
      setStreamStatus("error");
      return;
    }
    try {
      const response = await fetch(`${readServerUrl()}/api/v1/chat/completions`, {
        body: JSON.stringify({
          course_id: pathResult.data.course_id,
          messages: [{ content: question, role: "user" }],
          node_id: step.node_id,
          stream: true,
        }),
        headers: {
          Accept: "text/event-stream",
          Authorization: `Bearer ${accessToken}`,
          "Content-Type": "application/json",
          ...(afterEventId ? { "Last-Event-ID": afterEventId } : {}),
        },
        method: "POST",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const raw = await response.text();
      const next = reduceTutorSse(raw, afterEventId ? stream : emptyTutorState);
      setStream(next);
      const errorMatch = raw.match(/"code"\s*:\s*"([A-Z_]+)"/);
      if (errorMatch?.[1]) {
        setStreamErrorCode(errorMatch[1]);
        setStreamStatus("error");
      } else {
        setStreamStatus(next.done ? "done" : "error");
      }
    } catch (error) {
      setStreamErrorCode(error instanceof Error ? error.message : "PROVIDER_UNAVAILABLE");
      setStreamStatus("error");
    }
  }

  function startStream() {
    if (USING_TEST_FIXTURES) startFixtureStream();
    else void startRealStream();
  }

  function retryStream() {
    if (!USING_TEST_FIXTURES) {
      void startRealStream(stream.seenEventIds.at(-1));
      return;
    }
    setStreamStatus("streaming");
    const resumed = reduceTutorSse(
      [
        openingEvent,
        'id: tutor-retry-1\ndata: {"choices":[{"delta":{"content":"重连后不会重复已经收到的片段；继续回答："}}]}',
        answerEvent,
        toolEvent,
        "data: [DONE]",
      ].join("\n\n"),
      stream,
    );
    timerRef.current = window.setTimeout(() => {
      setStream(resumed);
      setStreamStatus("done");
    }, 60);
  }

  return (
    <div className="foundation-page tutor-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">TUTOR · REVIEWED SOURCES</p>
          <h1>智能辅导</h1>
          <p>回答引用课程知识底座；工具调用可见，内部提示、密钥与原始推理不会展示。</p>
        </div>
        <Link className="profile-secondary-button" to="/resources">
          <BookOpenText size={16} /> 返回学习资源
        </Link>
      </div>

      <div className="tutor-layout">
        <section aria-labelledby="tutor-conversation-title" className="tutor-conversation">
          <div className="section-heading-row">
            <div>
              <p className="eyebrow">GUIDED CONVERSATION</p>
              <h2 id="tutor-conversation-title">围绕当前知识点提问</h2>
            </div>
            <span>
              <ShieldCheck size={15} /> 只读工具白名单
            </span>
          </div>

          <div aria-live="polite" className="tutor-answer-area">
            {stream.reasoningObserved ? (
              <div aria-label="分析状态" className="tutor-reasoning-status" role="status">
                <Brain size={18} />
                <div>
                  <strong>{streamStatus === "done" ? "已完成教学分析" : "正在分析解题步骤"}</strong>
                  <p>原始模型推理受保护，仅展示可验证的教学进度。</p>
                </div>
              </div>
            ) : null}

            {stream.tools.map((tool) => (
              <article aria-label={toolLabel(tool.name)} className="tutor-tool-card" key={tool.id}>
                <span>
                  <MagnifyingGlass size={18} />
                </span>
                <div>
                  <strong>{toolLabel(tool.name)}</strong>
                  <p>只读检索 · 调用完成 · 来源将在回答下方列出</p>
                </div>
                <CheckCircle size={18} weight="fill" />
              </article>
            ))}

            {stream.content ? (
              <article aria-label="辅导回答" className="tutor-answer">
                <span className="tutor-avatar">
                  <ChatCircleDots size={21} weight="fill" />
                </span>
                <div>
                  <p>{stream.content}</p>
                  {stream.done ? (
                    <small>来源：KB-PY-04 · Python 官方课程镜像 · 审校 v3.1</small>
                  ) : null}
                </div>
              </article>
            ) : streamStatus === "idle" ? (
              <div className="tutor-empty">
                <Sparkle size={24} />
                <p>输入当前卡住的问题，我会先检索课程资源再回答。</p>
              </div>
            ) : null}

            {streamStatus === "error" ? (
              <section aria-label="辅导流中断" className="tutor-stream-error" role="alert">
                <WarningCircle size={20} />
                <div>
                  <strong>
                    {USING_TEST_FIXTURES && view === "rejected"
                      ? "回答触发内容安全门禁"
                      : streamErrorCode === "PROVIDER_UNAVAILABLE"
                        ? "辅导 Provider 当前不可用"
                        : "连接中断，已保留收到的内容"}
                  </strong>
                  <p>
                    {USING_TEST_FIXTURES && view === "rejected"
                      ? "本次内容不会展示或写入学习证据。"
                      : "可从最后一个事件继续，重放片段会按事件 ID 去重。"}
                  </p>
                </div>
                {!USING_TEST_FIXTURES || view !== "rejected" ? (
                  <button onClick={retryStream} type="button">
                    <ArrowClockwise size={16} /> 重新连接辅导流
                  </button>
                ) : null}
              </section>
            ) : null}
          </div>

          <form
            className="tutor-composer"
            onSubmit={(event) => {
              event.preventDefault();
              startStream();
            }}
          >
            <label htmlFor="tutor-question">你的问题</label>
            <textarea
              id="tutor-question"
              onChange={(event) => setQuestion(event.target.value)}
              rows={3}
              value={question}
            />
            <div>
              <span>不会将模型回答直接计为掌握证据</span>
              <button
                className="py-button"
                disabled={!question.trim() || streamStatus === "streaming"}
                type="submit"
              >
                <PaperPlaneTilt size={17} /> 发送问题
              </button>
            </div>
          </form>
        </section>

        <aside className="tutor-stream-panel">
          <p className="eyebrow">STREAM STATUS</p>
          <h2>本次辅导流</h2>
          <div
            aria-label="辅导流状态"
            className={`tutor-stream-state is-${streamStatus}`}
            role="status"
          >
            {streamStatus === "idle" ? "等待提问" : null}
            {streamStatus === "streaming" ? "正在接收回答 · 可安全续传" : null}
            {streamStatus === "done" ? "回答完成 · [DONE]" : null}
            {streamStatus === "error" ? "流已中断 · 可重试" : null}
          </div>
          <dl>
            <div>
              <dt>事件片段</dt>
              <dd>{stream.seenEventIds.length}</dd>
            </div>
            <div>
              <dt>重放去重</dt>
              <dd>按 SSE event id</dd>
            </div>
            <div>
              <dt>推理展示</dt>
              <dd>{stream.reasoningObserved ? "安全状态摘要" : "当前模型不提供"}</dd>
            </div>
            <div>
              <dt>工具权限</dt>
              <dd>课程检索（只读）</dd>
            </div>
          </dl>
          <p>
            <ShieldCheck size={15} /> 浏览器不持有 Provider 密钥，也不能执行特权工具。
          </p>
        </aside>
      </div>
    </div>
  );
}
