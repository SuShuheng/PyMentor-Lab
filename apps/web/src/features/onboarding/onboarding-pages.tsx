import { ChartFrame } from "@pymentor/charts";
import {
  ArrowRight,
  ChatCircleDots,
  ClockCounterClockwise,
  FileMagnifyingGlass,
  ShieldCheck,
  X,
} from "@phosphor-icons/react";
import {
  client,
  disputeProfileApiV1ProfilesDisputesPost,
  getCurrentProfileApiV1ProfilesCurrentGet,
  type ProfileDimensionContract,
  type ProfileSnapshot,
} from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";
import { StatePanel } from "@pymentor/ui";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useAuth } from "../auth/auth-session";

const ONBOARDING_STEP_KEY = "pymentor.onboardingStep";

const questions = [
  {
    prompt: "你之前接触过 Python 吗？",
    help: "这只影响诊断起点，不会直接决定能力分数。",
    choices: ["第一次学习", "有一点基础", "做过完整项目"],
  },
  {
    prompt: "你这学期最希望解决什么问题？",
    help: "可以选择最接近的一项，后续仍可修改学习目标。",
    choices: ["跟上课堂进度", "独立完成作业", "准备竞赛或项目"],
  },
  {
    prompt: "遇到报错时，你通常先怎么做？",
    help: "我们会结合后续真实代码证据验证，而不是仅凭回答打分。",
    choices: ["阅读错误信息", "逐行检查代码", "先请求提示"],
  },
  {
    prompt: "下面哪类练习对你最有帮助？",
    help: "资源偏好只用于推荐排序，不会改变正式掌握状态。",
    choices: ["短小例题", "可运行代码", "图解与执行轨迹"],
  },
  {
    prompt: "每周可以稳定安排多少学习时间？",
    help: "学习计划会保留弹性，可随时暂停或重新安排。",
    choices: ["少于 2 小时", "2–4 小时", "4 小时以上"],
  },
] as const;

const dimensionLabels: Record<ProfileDimensionContract, string> = {
  CONCEPT_KNOWLEDGE: "概念知识掌握",
  DEBUGGING: "调试与错误定位能力",
  DECOMPOSITION: "问题分解与算法表达能力",
  EXECUTION_MODEL: "代码执行模型",
  IMPLEMENTATION: "编程实现能力",
  INDEPENDENCE_SUPPORT: "独立完成度与支架需求",
  TESTING: "测试与边界意识",
  TRANSFER: "迁移与综合应用能力",
};

function configureProfileClient(): void {
  client.setConfig({
    baseUrl: readServerUrl(),
    credentials: "include",
    fetch,
  });
}

function profileError(error: unknown): string {
  if (error && typeof error === "object") {
    const message = Reflect.get(error, "message");
    if (typeof message === "string") return message;
  }
  return "画像服务暂时不可用，请稍后重试";
}

function commandKey(prefix: string): string {
  return `${prefix}-${globalThis.crypto.randomUUID()}`;
}

function loadStep(): number {
  const stored = Number(window.localStorage.getItem(ONBOARDING_STEP_KEY) ?? 0);
  return Number.isInteger(stored) && stored >= 0 && stored < questions.length ? stored : 0;
}

export function OnboardingPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [step, setStep] = useState(loadStep);
  const [answers, setAnswers] = useState<string[]>([]);
  const view = searchParams.get("view");

  if (view === "reconnecting") {
    return (
      <div className="foundation-page onboarding-page">
        <StatePanel
          actionLabel="立即重连"
          description="已保留当前对话进度，连接恢复后将从原步骤继续"
          onAction={() => setSearchParams({})}
          state="offline"
          title="正在重新连接"
        />
      </div>
    );
  }

  if (view === "incomplete") {
    return (
      <div className="foundation-page onboarding-page">
        <StatePanel
          actionLabel="继续诊断"
          description="回答不足时不会生成正式画像版本，已完成内容仍会保留"
          onAction={() => setSearchParams({})}
          state="error"
          title="诊断尚未完成"
        />
      </div>
    );
  }

  const complete = step >= questions.length;
  const currentQuestion = questions[Math.min(step, questions.length - 1)]!;

  return (
    <div className="foundation-page onboarding-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">ONBOARDING · 对话式诊断</p>
          <h1>建立你的学习画像</h1>
          <p>用 5 个轻量问题确定诊断起点，正式画像只由后续证据更新</p>
        </div>
        <span className="status-chip">
          <ShieldCheck size={15} /> 证据驱动
        </span>
      </div>

      <section className="onboarding-workspace" aria-labelledby="onboarding-conversation-title">
        <aside className="onboarding-summary">
          <span className="onboarding-summary__icon">
            <ChatCircleDots size={28} />
          </span>
          <h2 id="onboarding-conversation-title">初始学习访谈</h2>
          <p>约 3 分钟 · 随时可以退出，进度会保存在当前设备。</p>
          <div aria-label="对话进度" className="onboarding-progress-copy" role="status">
            {complete ? "对话已完成" : `第 ${step + 1} 步，共 ${questions.length} 步`}
          </div>
          <progress
            aria-label="画像构建进度"
            aria-valuemax={questions.length}
            aria-valuemin={1}
            aria-valuenow={complete ? questions.length : step + 1}
            max={questions.length}
            value={complete ? questions.length : step + 1}
          />
          <ul>
            <li>
              <FileMagnifyingGlass size={17} /> 回答用于选择诊断题
            </li>
            <li>
              <ClockCounterClockwise size={17} /> 可恢复未完成进度
            </li>
            <li>
              <ShieldCheck size={17} /> Agent 不直接写正式画像
            </li>
          </ul>
        </aside>

        <div className="onboarding-conversation" aria-live="polite">
          <div className="conversation-history">
            <div className="conversation-message conversation-message--assistant">
              <span aria-hidden="true">PM</span>
              <p>你好，我会先了解你的目标与学习习惯。每个判断都需要后续学习证据验证。</p>
            </div>
            {answers.map((answer, index) => (
              <div
                className="conversation-message conversation-message--student"
                key={`${answer}-${index}`}
              >
                <p>{answer}</p>
              </div>
            ))}
          </div>

          {complete ? (
            <div className="onboarding-complete">
              <ShieldCheck size={34} weight="fill" />
              <h2>初始上下文已建立</h2>
              <p>下一步会用短练习补齐诊断；证据不足的维度将标记为“待观察”。</p>
              <Link className="py-button" to="/growth/profile">
                查看初始画像
              </Link>
            </div>
          ) : (
            <div className="onboarding-question">
              <p className="eyebrow">问题 {step + 1}</p>
              <h2>{currentQuestion.prompt}</h2>
              <p>{currentQuestion.help}</p>
              <div className="onboarding-choices">
                {currentQuestion.choices.map((choice) => (
                  <button
                    key={choice}
                    onClick={() => {
                      const nextStep = step + 1;
                      setAnswers((current) => [...current, choice]);
                      setStep(nextStep);
                      window.localStorage.setItem(
                        ONBOARDING_STEP_KEY,
                        String(Math.min(nextStep, questions.length)),
                      );
                    }}
                    type="button"
                  >
                    <span>{choice}</span>
                    <ArrowRight size={18} />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

export function ProfilePage() {
  const { session } = useAuth();
  const accessToken = session?.accessToken;
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [disputeOpen, setDisputeOpen] = useState(false);
  const [disputeState, setDisputeState] = useState<"error" | "idle" | "submitted" | "submitting">(
    "idle",
  );
  const [disputeError, setDisputeError] = useState<string | null>(null);
  const [profile, setProfile] = useState<ProfileSnapshot | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setProfile(null);
    setLoadError(null);
    if (!accessToken) {
      setLoadError("登录会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    configureProfileClient();
    void getCurrentProfileApiV1ProfilesCurrentGet({
      headers: { Authorization: `Bearer ${accessToken}` },
    })
      .then((result) => {
        if (!active) return;
        if (!result.data) {
          throw new Error(
            result.response.status === 404
              ? "尚未生成正式画像，请先完成诊断与学习任务"
              : profileError(result.error),
          );
        }
        setProfile(result.data);
      })
      .catch((error: unknown) => {
        if (active) setLoadError(profileError(error));
      });
    return () => {
      active = false;
    };
  }, [accessToken, loadAttempt]);

  const dimensionItems = useMemo(
    () =>
      profile?.dimensions.map((item) => ({
        ...item,
        evidence: profile.source_event_id,
        name: dimensionLabels[item.dimension],
        nodes: item.scope_key,
        score: Math.round(item.score * 100),
      })) ?? [],
    [profile],
  );
  const rows = useMemo(
    () => dimensionItems.map((item) => [item.name, `${item.score}`, item.nodes] as const),
    [dimensionItems],
  );

  if (loadError) {
    return (
      <div className="foundation-page profile-page">
        <StatePanel
          actionLabel="重新加载"
          description={loadError}
          onAction={() => setLoadAttempt((attempt) => attempt + 1)}
          state="error"
          title="无法读取学习画像"
        />
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="foundation-page profile-page">
        <StatePanel
          description="正在从服务器读取正式画像版本与证据来源"
          state="loading"
          title="加载学习画像"
        />
      </div>
    );
  }

  return (
    <div className="foundation-page profile-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">GROWTH · EVIDENCE PROFILE</p>
          <h1>我的学习画像</h1>
          <p>每个分数都可追溯到知识节点与学习证据，浏览器不重新计算正式状态</p>
        </div>
        <span className="status-chip">画像版本 v{profile.version}</span>
      </div>

      <div className="profile-layout">
        <ChartFrame
          columns={["能力维度", "分数", "知识节点 / 能力簇"]}
          description={`能力维度按知识节点聚合，0 到 100 分；分数来自画像版本 v${profile.version}。`}
          rows={rows}
          title="八维能力画像"
        >
          <div className="profile-bars">
            {dimensionItems.map((item) => (
              <div className="profile-bar" key={item.name}>
                <span>{item.name}</span>
                <span>
                  <i style={{ width: `${item.score}%` }} />
                </span>
                <strong>{item.score}</strong>
              </div>
            ))}
          </div>
        </ChartFrame>

        <aside className="profile-version-card">
          <p className="eyebrow">PROFILE VERSION</p>
          <h2>画像版本 v{profile.version}</h2>
          <dl>
            <div>
              <dt>画像 ID</dt>
              <dd>{profile.id}</dd>
            </div>
            <div>
              <dt>来源事件</dt>
              <dd>{profile.source_event_id}</dd>
            </div>
            <div>
              <dt>能力维度</dt>
              <dd>{profile.dimensions.length} 个服务器维度</dd>
            </div>
            <div>
              <dt>聚合方式</dt>
              <dd>按知识节点聚合</dd>
            </div>
          </dl>
          <p className="profile-rule-note">Agent 仅提出画像候选，正式版本由确定性规则组件写入。</p>
          <button
            className="profile-secondary-button"
            onClick={() => setEvidenceOpen((open) => !open)}
            type="button"
          >
            <FileMagnifyingGlass size={17} /> {evidenceOpen ? "收起画像证据" : "查看画像证据"}
          </button>
          <button
            className="profile-secondary-button"
            onClick={() => {
              setDisputeError(null);
              setDisputeState("idle");
              setDisputeOpen(true);
            }}
            type="button"
          >
            对画像提出异议
          </button>
          {disputeState === "submitted" ? (
            <p aria-label="异议状态" className="profile-dispute-status" role="status">
              异议已提交 · 审核前画像版本保持不变
            </p>
          ) : null}
        </aside>
      </div>

      {evidenceOpen ? (
        <section aria-label="画像证据" className="profile-evidence" role="region">
          <div>
            <p className="eyebrow">EVIDENCE DISCLOSURE</p>
            <h2>本版本的代表性证据</h2>
            <p>默认只展示教学摘要；证据 ID 与规则信息在此按需展开。</p>
          </div>
          <ul>
            {dimensionItems.slice(0, 4).map((item, index) => (
              <li
                id={`evidence-${index}-${item.dimension}`}
                key={`${item.dimension}-${item.nodes}`}
              >
                <span>
                  <strong>{item.name}</strong>
                  <small>{item.nodes}</small>
                </span>
                <a href={`#evidence-${index}-${item.dimension}`}>{item.evidence}</a>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {disputeOpen ? (
        <div className="dialog-backdrop">
          <section
            aria-labelledby="profile-dispute-title"
            aria-modal="true"
            className="profile-dialog"
            role="dialog"
          >
            <button
              aria-label="关闭异议对话框"
              className="profile-dialog__close"
              onClick={() => setDisputeOpen(false)}
              type="button"
            >
              <X size={18} />
            </button>
            <p className="eyebrow">PROFILE REVIEW</p>
            <h2 id="profile-dispute-title">提交画像异议</h2>
            <p>请指出遗漏或错误的证据。提交后由规则与人工复核，当前画像不会被浏览器直接修改。</p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                const reason = new FormData(event.currentTarget).get("reason")?.toString().trim();
                if (!reason || !accessToken) return;
                setDisputeState("submitting");
                setDisputeError(null);
                configureProfileClient();
                void disputeProfileApiV1ProfilesDisputesPost({
                  body: { profile_version_id: profile.id, reason },
                  headers: {
                    Authorization: `Bearer ${accessToken}`,
                    "Idempotency-Key": commandKey("profile-dispute"),
                  },
                })
                  .then((result) => {
                    if (!result.response.ok) {
                      throw new Error(profileError(result.error));
                    }
                    setDisputeOpen(false);
                    setDisputeState("submitted");
                  })
                  .catch((error: unknown) => {
                    setDisputeError(profileError(error));
                    setDisputeState("error");
                  });
              }}
            >
              <label htmlFor="profile-dispute">异议说明</label>
              <textarea
                disabled={disputeState === "submitting"}
                id="profile-dispute"
                minLength={8}
                name="reason"
                required
                rows={5}
              />
              {disputeError ? (
                <p aria-label="异议提交错误" role="alert">
                  {disputeError}
                </p>
              ) : null}
              <div>
                <button
                  className="profile-secondary-button"
                  onClick={() => setDisputeOpen(false)}
                  type="button"
                >
                  取消
                </button>
                <button
                  className="py-button"
                  disabled={disputeState === "submitting"}
                  type="submit"
                >
                  {disputeState === "submitting" ? "提交中…" : "提交异议"}
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
    </div>
  );
}
