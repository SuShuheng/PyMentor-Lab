import {
  ArrowRight,
  CaretLeft,
  CaretRight,
  CheckCircle,
  ClockCounterClockwise,
  Code,
  Lightbulb,
  Play,
  Stop,
  TerminalWindow,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  cancelRunApiV1CodeRunsRunIdCancelPost,
  createRunApiV1CodeRunsPost,
  createSubmissionApiV1CodeSubmissionsPost,
  requestHintApiV1TasksTaskInstanceIdHintsPost,
  submitTaskApiV1TasksTaskInstanceIdSubmitPost,
  type CodeRunView,
  type TraceFrame,
} from "@pymentor/api-client";
import { StatePanel } from "@pymentor/ui";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";

import { commandHeaders, configureStudentApi, safeApiMessage } from "../../student-api";
import { useAuth } from "../auth/auth-session";
import { OcrScreenshotUpload } from "./ocr-screenshot-upload";

const USING_TEST_FIXTURES = import.meta.env.MODE === "test";

const starterCode = `def sum_even(numbers):
    total = 0
    for index in range(len(numbers)):
        if numbers[index] % 2 == 0:
            total += numbers[index]
    return total

print(sum_even([1, 2, 3, 4]))`;

const longOutput = Array.from(
  { length: 90 },
  (_, index) => `iteration ${index + 1}: total=${index * 2}`,
).join("\n");

function boundedOutput(value: string, limit = 2000): { output: string; truncated: boolean } {
  if (value.length <= limit) return { output: value, truncated: false };
  return { output: `${value.slice(0, limit)}\n…`, truncated: true };
}

type RunStatus = "cancelled" | "failed" | "idle" | "running" | "success";
type SubmissionStatus = "idle" | "submitting" | "submitted";

export function NotebookPage() {
  const { session } = useAuth();
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view");
  const taskInstanceId = searchParams.get("task_instance_id");
  const taskVersion = Number(searchParams.get("version") ?? "0");
  const [code, setCode] = useState(starterCode);
  const [runStatus, setRunStatus] = useState<RunStatus>(
    view === "long-output" ? "success" : "idle",
  );
  const [hintLevel, setHintLevel] = useState(0);
  const [submissionStatus, setSubmissionStatus] = useState<SubmissionStatus>("idle");
  const [run, setRun] = useState<CodeRunView | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [submissionMessage, setSubmissionMessage] = useState<string | null>(null);
  const [hintContent, setHintContent] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);
  const submissionTimerRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      if (submissionTimerRef.current !== null) window.clearTimeout(submissionTimerRef.current);
    },
    [],
  );

  if (
    !USING_TEST_FIXTURES &&
    (!taskInstanceId || !Number.isInteger(taskVersion) || taskVersion < 1)
  ) {
    return (
      <StatePanel
        actionLabel="返回今日任务"
        description="请从服务端今日计划启动一个已发布任务"
        onAction={() => window.history.back()}
        state="error"
        title="缺少任务实例"
      />
    );
  }

  const output = boundedOutput(
    USING_TEST_FIXTURES ? (view === "long-output" ? longOutput : "6") : (run?.result?.stdout ?? ""),
  );
  const showResults = runStatus === "success";
  // FE-021: offer the OCR screenshot upload whenever the notebook is showing a
  // student-facing error (a real failed run, the user-error fixture, or a run
  // request that failed with a user-actionable message). Platform errors are
  // excluded — OCR-ing a "sandbox down" message adds nothing.
  const showOcrUpload =
    runStatus === "failed" ||
    view === "user-error" ||
    Boolean(operationError);

  async function runCode(): Promise<void> {
    setRunStatus("running");
    setSubmissionStatus("idle");
    setOperationError(null);
    if (USING_TEST_FIXTURES) {
      timerRef.current = window.setTimeout(() => {
        setRunStatus("success");
        timerRef.current = null;
      }, 80);
      return;
    }
    const accessToken = session?.accessToken;
    if (!accessToken || !taskInstanceId) {
      setOperationError("登录会话不可用");
      setRunStatus("failed");
      return;
    }
    configureStudentApi();
    try {
      const result = await createRunApiV1CodeRunsPost({
        body: {
          expected_task_version: taskVersion,
          mode: "RUN",
          source_code: code,
          task_instance_id: taskInstanceId,
          trace_enabled: false,
        },
        headers: commandHeaders(accessToken, "web-code-run"),
      });
      if (!result.data) {
        setOperationError(safeApiMessage(result.error));
        setRunStatus("failed");
        return;
      }
      setRun(result.data);
      setRunStatus(
        result.data.status === "COMPLETED"
          ? "success"
          : result.data.status === "CANCELLED"
            ? "cancelled"
            : "failed",
      );
    } catch (error) {
      setOperationError(safeApiMessage(error));
      setRunStatus("failed");
    }
  }

  async function cancelRun(): Promise<void> {
    if (USING_TEST_FIXTURES) {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      timerRef.current = null;
      setRunStatus("cancelled");
      setSubmissionStatus("idle");
      return;
    }
    const accessToken = session?.accessToken;
    if (!accessToken || !run) return;
    configureStudentApi();
    const result = await cancelRunApiV1CodeRunsRunIdCancelPost({
      headers: commandHeaders(accessToken, "web-code-cancel"),
      path: { run_id: run.run_id },
    });
    if (!result.data) {
      setOperationError(safeApiMessage(result.error));
      return;
    }
    setRun(result.data);
    setRunStatus("cancelled");
  }

  async function submitCode(): Promise<void> {
    setSubmissionStatus("submitting");
    setSubmissionMessage(null);
    if (USING_TEST_FIXTURES) {
      submissionTimerRef.current = window.setTimeout(() => {
        setSubmissionStatus("submitted");
        submissionTimerRef.current = null;
      }, 60);
      return;
    }
    const accessToken = session?.accessToken;
    if (!accessToken || !taskInstanceId) return;
    configureStudentApi();
    try {
      const result = await createSubmissionApiV1CodeSubmissionsPost({
        body: {
          expected_task_version: taskVersion,
          source_code: code,
          task_instance_id: taskInstanceId,
        },
        headers: commandHeaders(accessToken, "web-code-submit"),
      });
      if (!result.data) {
        setSubmissionStatus("idle");
        setOperationError(safeApiMessage(result.error));
        return;
      }
      setRun(result.data);
      if (!result.data.evidence_event_id) {
        setSubmissionStatus("idle");
        setSubmissionMessage("本次执行未产生可接受的评估证据，掌握状态保持不变");
        return;
      }

      const mastery = await submitTaskApiV1TasksTaskInstanceIdSubmitPost({
        body: {
          evidence_event_id: result.data.evidence_event_id,
          expected_task_version: taskVersion,
        },
        headers: commandHeaders(accessToken, "web-task-submit"),
        path: { task_instance_id: taskInstanceId },
      });
      if (!mastery.data) {
        setSubmissionStatus("idle");
        setOperationError(safeApiMessage(mastery.error));
        return;
      }
      setSubmissionStatus("submitted");
      setSubmissionMessage(
        `提交成功 · 掌握状态 ${mastery.data.status}${
          mastery.data.review_due_at ? ` · 复习时间 ${mastery.data.review_due_at}` : ""
        }`,
      );
    } catch (error) {
      setSubmissionStatus("idle");
      setOperationError(safeApiMessage(error));
    }
  }

  async function requestHint(): Promise<void> {
    if (USING_TEST_FIXTURES) {
      setHintLevel((level) => Math.min(3, level + 1));
      return;
    }
    const accessToken = session?.accessToken;
    if (!accessToken || !taskInstanceId) return;
    configureStudentApi();
    const result = await requestHintApiV1TasksTaskInstanceIdHintsPost({
      body: { expected_task_version: taskVersion, level: Math.min(3, hintLevel + 1) },
      headers: commandHeaders(accessToken, `web-hint-${hintLevel + 1}`),
      path: { task_instance_id: taskInstanceId },
    });
    if (!result.data) {
      setOperationError(safeApiMessage(result.error));
      return;
    }
    setHintLevel(result.data.level);
    setHintContent(result.data.content);
  }

  return (
    <div className="foundation-page notebook-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">CODE LAB · CONTROLLED NOTEBOOK</p>
          <h1>代码实验</h1>
          <p>在安全沙箱中运行、测试与保留每次修订；测试通过不直接改变掌握状态</p>
        </div>
        <Link
          className="profile-secondary-button notebook-trace-link"
          state={{ sourceCode: code }}
          to={
            USING_TEST_FIXTURES
              ? "/lab/trace"
              : `/lab/trace?task_instance_id=${encodeURIComponent(taskInstanceId ?? "")}&version=${taskVersion}`
          }
        >
          <ClockCounterClockwise size={16} /> 打开执行轨迹
        </Link>
      </div>

      <section aria-label="任务说明" className="notebook-task-brief">
        <div>
          <p className="eyebrow">TASK · LOOP-BOUNDARY-04</p>
          <h2>实现偶数求和函数</h2>
          <p>返回列表中所有偶数之和。空列表应返回 0，不得修改输入列表。</p>
        </div>
        <dl>
          <div>
            <dt>预计</dt>
            <dd>20 分钟</dd>
          </div>
          <div>
            <dt>提示预算</dt>
            <dd>{hintLevel} / 3</dd>
          </div>
          <div>
            <dt>修订</dt>
            <dd>v3</dd>
          </div>
        </dl>
      </section>

      <div className="notebook-layout">
        <section className="code-editor-panel" aria-labelledby="code-editor-title">
          <div className="code-panel-header">
            <span>
              <Code size={17} /> main.py
            </span>
            <small>Python 3.12 · UTF-8</small>
          </div>
          <h2 className="sr-only" id="code-editor-title">
            Python 代码编辑器
          </h2>
          <textarea
            aria-label="Python 代码编辑器"
            onChange={(event) => {
              setCode(event.target.value);
              setRunStatus("idle");
              setSubmissionStatus("idle");
            }}
            spellCheck="false"
            value={code}
          />
          <div className="notebook-actions">
            <div className="notebook-action-buttons">
              {runStatus === "running" ? (
                <button
                  className="notebook-cancel-button"
                  onClick={() => void cancelRun()}
                  type="button"
                >
                  <Stop size={16} weight="fill" /> 取消运行
                </button>
              ) : (
                <button className="py-button" onClick={() => void runCode()} type="button">
                  <Play size={16} weight="fill" /> 运行代码
                </button>
              )}
              <button
                aria-label="提交本次练习"
                className="notebook-submit-button"
                disabled={runStatus !== "success" || submissionStatus === "submitting"}
                onClick={() => void submitCode()}
                type="button"
              >
                <ArrowRight size={16} />
                {submissionStatus === "submitting" ? "提交中…" : "提交本次练习"}
              </button>
            </div>
            <div className="notebook-action-meta">
              <span>自动保存 · 最近保存 11:41:08</span>
              {submissionStatus !== "idle" ? (
                <p aria-label="提交状态" role="status">
                  {submissionStatus === "submitting"
                    ? "正在提交已测试版本 v3…"
                    : (submissionMessage ?? "提交成功 · SUB-LOOP-2407 · 提交不会直接改变掌握状态")}
                </p>
              ) : null}
            </div>
          </div>
        </section>

        <aside className="notebook-side-panel">
          <section aria-labelledby="hint-title" className="notebook-panel-card">
            <div className="notebook-card-heading">
              <span>
                <Lightbulb size={18} />
              </span>
              <div>
                <h2 id="hint-title">分层提示</h2>
                <p>每次使用都会写入提示证据</p>
              </div>
            </div>
            <p className="hint-budget">提示预算 {hintLevel} / 3</p>
            {hintLevel > 0 ? (
              <p aria-label="提示内容" className="hint-content" role="status">
                {hintContent ?? "先检查循环范围是否覆盖了最后一个元素，再考虑偶数判断。"}
              </p>
            ) : null}
            <button disabled={hintLevel >= 3} onClick={() => void requestHint()} type="button">
              使用一级提示
            </button>
          </section>
          <section aria-labelledby="revision-title" className="notebook-panel-card">
            <div className="notebook-card-heading">
              <span>
                <ClockCounterClockwise size={18} />
              </span>
              <div>
                <h2 id="revision-title">修订历史</h2>
                <p>可查看但不覆盖当前代码</p>
              </div>
            </div>
            <ol aria-label="代码修订历史" className="revision-list">
              <li>
                <button type="button">
                  <strong>v3 · 当前版本</strong>
                  <small>11:41 · 修正循环范围</small>
                </button>
              </li>
              <li>
                <button type="button">
                  <strong>v2</strong>
                  <small>11:38 · 加入偶数判断</small>
                </button>
              </li>
              <li>
                <button type="button">
                  <strong>v1</strong>
                  <small>11:34 · 初始代码</small>
                </button>
              </li>
            </ol>
          </section>
        </aside>
      </div>

      <section className="notebook-results" aria-labelledby="results-title">
        <div className="code-panel-header">
          <span>
            <TerminalWindow size={17} /> <strong id="results-title">运行与测试结果</strong>
          </span>
          <small>RUN-9C17</small>
        </div>
        {runStatus !== "idle" ? (
          <div
            aria-label="运行状态"
            className={`run-status run-status--${runStatus}`}
            role="status"
          >
            {runStatus === "running" ? "正在安全沙箱中运行…" : null}
            {runStatus === "cancelled" ? "运行已取消，没有生成测试或学习证据" : null}
            {runStatus === "success" ? "运行完成 · 退出码 0 · 428 ms" : null}
            {runStatus === "failed" ? "运行失败 · 未生成正式掌握结论" : null}
          </div>
        ) : null}

        {operationError ? (
          <div
            aria-label="平台运行失败"
            className="notebook-error notebook-error--platform"
            role="alert"
          >
            <WarningCircle size={20} />
            <div>
              <strong>运行请求失败</strong>
              <p>{operationError}</p>
            </div>
          </div>
        ) : null}

        {view === "user-error" ? (
          <div
            aria-label="代码运行错误"
            className="notebook-error notebook-error--user"
            role="alert"
          >
            <WarningCircle size={20} />
            <div>
              <strong>代码运行错误</strong>
              <pre>IndexError: list index out of range\n at main.py:4</pre>
              <p>这是代码错误，可用于后续反馈与修订证据。</p>
            </div>
          </div>
        ) : null}
        {view === "platform-error" ? (
          <div
            aria-label="平台运行失败"
            className="notebook-error notebook-error--platform"
            role="alert"
          >
            <WarningCircle size={20} />
            <div>
              <strong>平台运行失败</strong>
              <p>沙箱暂时不可用，本次不会计入学习证据。请稍后重试。</p>
            </div>
          </div>
        ) : null}

        {showOcrUpload ? (
          <OcrScreenshotUpload accessToken={session?.accessToken} />
        ) : null}

        {showResults && view !== "user-error" && view !== "platform-error" ? (
          <div className="notebook-result-grid">
            <div>
              <h3>程序输出</h3>
              <pre aria-label="程序输出" role="log">
                {output.output}
                {output.truncated ? "\n输出已截断（保留前 2000 字符）" : ""}
              </pre>
            </div>
            <div>
              <h3>测试</h3>
              {USING_TEST_FIXTURES ? (
                <>
                  <ul aria-label="可见测试结果" className="test-result-list">
                    <li>
                      <CheckCircle size={16} weight="fill" /> 3 / 3 通过
                    </li>
                    <li>✓ 普通列表 [1, 2, 3, 4]</li>
                    <li>✓ 空列表 []</li>
                    <li>✓ 仅奇数 [1, 3, 5]</li>
                  </ul>
                  <p className="hidden-test-result">隐藏测试：2 / 2 通过（测试内容不公开）</p>
                </>
              ) : (
                <>
                  <ul aria-label="可见测试结果" className="test-result-list">
                    {(run?.result?.tests ?? [])
                      .filter((item) => item.visibility === "VISIBLE")
                      .map((item) => (
                        <li key={item.case_id}>
                          {item.passed ? (
                            <CheckCircle size={16} weight="fill" />
                          ) : (
                            <WarningCircle size={16} />
                          )}{" "}
                          {item.display_name} · {item.passed ? "通过" : "未通过"}
                        </li>
                      ))}
                  </ul>
                  <p className="hidden-test-result">
                    隐藏测试：
                    {
                      (run?.result?.tests ?? []).filter(
                        (item) => item.visibility === "HIDDEN" && item.passed,
                      ).length
                    }{" "}
                    /{" "}
                    {
                      (run?.result?.tests ?? []).filter((item) => item.visibility === "HIDDEN")
                        .length
                    }{" "}
                    通过（测试内容不公开）
                  </p>
                </>
              )}
              <p className="mastery-boundary-note">
                测试通过不等于知识已掌握；需结合修订、提示与到期复测证据。
              </p>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}

const traceFrames = [
  {
    line: 1,
    event: "调用函数",
    variables: "numbers = [1, 2, 3, 4]",
    output: "",
  },
  { line: 2, event: "初始化变量", variables: "total = 0", output: "" },
  {
    line: 3,
    event: "进入循环",
    variables: "index = 0 · total = 0",
    output: "",
  },
  {
    line: 4,
    event: "判断偶数",
    variables: "numbers[0] = 1 · False",
    output: "",
  },
] as const;

export function TracePage() {
  const { session } = useAuth();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const taskInstanceId = searchParams.get("task_instance_id");
  const taskVersion = Number(searchParams.get("version") ?? "0");
  const navigationState = location.state as { sourceCode?: unknown } | null;
  const sourceCode =
    typeof navigationState?.sourceCode === "string" ? navigationState.sourceCode : starterCode;
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [prediction, setPrediction] = useState("");
  const [predictionSaved, setPredictionSaved] = useState(false);
  const [serverFrames, setServerFrames] = useState<TraceFrame[]>([]);
  const [traceStatus, setTraceStatus] = useState<"error" | "loading" | "ready">(
    USING_TEST_FIXTURES ? "ready" : "loading",
  );
  const [traceError, setTraceError] = useState<string | null>(null);
  const startedRef = useRef(false);
  const activeFrames = USING_TEST_FIXTURES
    ? traceFrames
    : serverFrames.map((item) => ({
        event: `${item.event} · ${item.func_name}`,
        line: item.line,
        output: "",
        variables: item.locals
          ? Object.entries(item.locals)
              .map(([name, value]) => `${name} = ${value}`)
              .join(" · ")
          : "无可见局部变量",
      }));
  const frame = activeFrames[step];

  useEffect(() => {
    if (USING_TEST_FIXTURES || startedRef.current) return;
    if (!taskInstanceId || !Number.isInteger(taskVersion) || taskVersion < 1) {
      setTraceStatus("error");
      setTraceError("请从代码实验页面打开一个有效的任务轨迹");
      return;
    }
    const accessToken = session?.accessToken;
    if (!accessToken) return;
    startedRef.current = true;
    configureStudentApi();
    void createRunApiV1CodeRunsPost({
      body: {
        expected_task_version: taskVersion,
        mode: "TRACE",
        source_code: sourceCode,
        task_instance_id: taskInstanceId,
        trace_enabled: true,
      },
      headers: commandHeaders(accessToken, "web-code-trace"),
    })
      .then((result) => {
        const frames = result.data?.result?.trace_frames ?? [];
        if (!result.data) throw new Error(safeApiMessage(result.error));
        if (result.data.status !== "COMPLETED" || frames.length === 0) {
          throw new Error(
            result.data.result?.user_error ??
              result.data.result?.platform_error ??
              "沙箱未返回可见轨迹帧",
          );
        }
        setServerFrames(frames);
        setTraceStatus("ready");
      })
      .catch((error: unknown) => {
        setTraceError(safeApiMessage(error));
        setTraceStatus("error");
      });
  }, [session?.accessToken, sourceCode, taskInstanceId, taskVersion]);

  useEffect(() => {
    if (!playing || activeFrames.length === 0) return;
    const timer = window.setInterval(() => {
      setStep((current) => {
        if (current >= activeFrames.length - 1) {
          setPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, 700);
    return () => window.clearInterval(timer);
  }, [activeFrames.length, playing]);

  if (traceStatus === "loading") {
    return (
      <StatePanel
        description="正在由服务端安全沙箱生成确定性关键帧"
        state="loading"
        title="生成执行轨迹"
      />
    );
  }
  if (traceStatus === "error" || !frame) {
    return (
      <StatePanel
        actionLabel="返回代码实验"
        description={traceError ?? "没有可显示的执行轨迹"}
        onAction={() => window.history.back()}
        state="error"
        title="轨迹不可用"
      />
    );
  }

  const notebookHref = USING_TEST_FIXTURES
    ? "/lab"
    : `/lab?task_instance_id=${encodeURIComponent(taskInstanceId ?? "")}&version=${taskVersion}`;

  return (
    <div className="foundation-page trace-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">TRACE · DETERMINISTIC FRAMES</p>
          <h1>代码执行轨迹</h1>
          <p>逐步查看服务端生成的确定性关键帧，并提交下一步预测</p>
        </div>
        <Link
          className="profile-secondary-button notebook-trace-link"
          state={{ sourceCode }}
          to={notebookHref}
        >
          返回 Notebook
        </Link>
      </div>
      <div className="trace-toolbar">
        <button
          aria-label="上一步"
          disabled={step === 0}
          onClick={() => setStep((current) => Math.max(0, current - 1))}
          type="button"
        >
          <CaretLeft size={18} />
        </button>
        <button
          aria-label={playing ? "暂停播放" : "播放轨迹"}
          onClick={() => setPlaying((value) => !value)}
          type="button"
        >
          {playing ? <Stop size={17} /> : <Play size={17} weight="fill" />}
        </button>
        <button
          aria-label="下一步"
          disabled={step === activeFrames.length - 1}
          onClick={() => setStep((current) => Math.min(activeFrames.length - 1, current + 1))}
          type="button"
        >
          <CaretRight size={18} />
        </button>
        <input
          aria-label="轨迹步进"
          max={activeFrames.length}
          min={1}
          onChange={(event) => setStep(Number(event.target.value) - 1)}
          type="range"
          value={step + 1}
        />
        <span aria-label="当前轨迹步骤" role="status">
          步骤 {step + 1} / {activeFrames.length}
        </span>
      </div>
      <div className="trace-layout">
        <section className="trace-code-panel" aria-labelledby="trace-code-title">
          <div className="code-panel-header">
            <span>
              <Code size={17} /> <strong id="trace-code-title">main.py</strong>
            </span>
            <small>只读关键帧</small>
          </div>
          <ol>
            {sourceCode
              .split("\n")
              .slice(0, 6)
              .map((line, index) => (
                <li
                  className={index + 1 === frame.line ? "is-active" : ""}
                  key={`${line}-${index}`}
                >
                  <span>{index + 1}</span>
                  <code>{line || " "}</code>
                </li>
              ))}
          </ol>
        </section>
        <aside className="trace-state-panel">
          <p className="eyebrow">FRAME {step + 1}</p>
          <h2>{frame.event}</h2>
          <dl>
            <div>
              <dt>当前行</dt>
              <dd>{frame.line}</dd>
            </div>
            <div>
              <dt>变量</dt>
              <dd>{frame.variables}</dd>
            </div>
            <div>
              <dt>输出</dt>
              <dd>{frame.output || "暂无输出"}</dd>
            </div>
          </dl>
          <p className="trace-state-note">关键帧来自沙箱 instrumentation，不由浏览器推测。</p>
        </aside>
      </div>
      <section className="trace-prediction" aria-labelledby="prediction-title">
        <div>
          <p className="eyebrow">PREDICTION EVIDENCE</p>
          <h2 id="prediction-title">下一关键帧会发生什么？</h2>
          <p>预测结果用于“代码执行模型”维度证据，不会单独决定掌握。</p>
        </div>
        {USING_TEST_FIXTURES ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              setPredictionSaved(true);
            }}
          >
            {["i 将变为 2", "total 将变为 1", "函数立即返回"].map((choice) => (
              <label key={choice}>
                <input
                  checked={prediction === choice}
                  name="prediction"
                  onChange={() => setPrediction(choice)}
                  required
                  type="radio"
                />{" "}
                {choice}
              </label>
            ))}
            <button className="py-button" disabled={!prediction} type="submit">
              提交关键帧预测 <ArrowRight size={16} />
            </button>
          </form>
        ) : (
          <p className="mastery-boundary-note" role="note">
            当前服务端尚未提供预测证据写入契约；本页只展示已持久化代码运行关联的沙箱轨迹，不会伪造预测证据。
          </p>
        )}
        {USING_TEST_FIXTURES && predictionSaved ? (
          <p aria-label="预测证据状态" className="profile-dispute-status" role="status">
            预测已记录为证据 EVD-TRACE-302 · 等待完整轨迹结束后评分
          </p>
        ) : null}
      </section>
    </div>
  );
}
