import { ChartFrame } from "@pymentor/charts";
import {
  ArrowRight,
  ChatCircleDots,
  ClockCounterClockwise,
  FileMagnifyingGlass,
  ShieldCheck,
  X,
} from "@phosphor-icons/react";
import { StatePanel } from "@pymentor/ui";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

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

const profileDimensions = [
  {
    name: "概念知识掌握",
    score: 76,
    nodes: "函数 82 · 循环 70",
    evidence: "EVD-2048",
  },
  {
    name: "代码执行模型",
    score: 68,
    nodes: "作用域 64 · 控制流 72",
    evidence: "EVD-2071",
  },
  {
    name: "编程实现能力",
    score: 73,
    nodes: "函数封装 78 · 列表处理 68",
    evidence: "EVD-2086",
  },
  {
    name: "问题分解与算法表达能力",
    score: 61,
    nodes: "步骤拆分 66 · 伪代码 56",
    evidence: "EVD-2093",
  },
  {
    name: "调试与错误定位能力",
    score: 70,
    nodes: "异常阅读 74 · 定位 66",
    evidence: "EVD-2104",
  },
  {
    name: "测试与边界意识",
    score: 58,
    nodes: "边界值 54 · 自测 62",
    evidence: "EVD-2112",
  },
  {
    name: "迁移与综合应用能力",
    score: 64,
    nodes: "变式迁移 60 · 综合任务 68",
    evidence: "EVD-2120",
  },
  {
    name: "独立完成度与支架需求",
    score: 72,
    nodes: "独立运行 76 · 提示预算 68",
    evidence: "EVD-2138",
  },
] as const;

function loadStep(): number {
  const stored = Number(window.localStorage.getItem(ONBOARDING_STEP_KEY) ?? 0);
  return Number.isInteger(stored) && stored >= 0 && stored < questions.length
    ? stored
    : 0;
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

      <section
        className="onboarding-workspace"
        aria-labelledby="onboarding-conversation-title"
      >
        <aside className="onboarding-summary">
          <span className="onboarding-summary__icon">
            <ChatCircleDots size={28} />
          </span>
          <h2 id="onboarding-conversation-title">初始学习访谈</h2>
          <p>约 3 分钟 · 随时可以退出，进度会保存在当前设备。</p>
          <div
            aria-label="对话进度"
            className="onboarding-progress-copy"
            role="status"
          >
            {complete
              ? "对话已完成"
              : `第 ${step + 1} 步，共 ${questions.length} 步`}
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
              <p>
                你好，我会先了解你的目标与学习习惯。每个判断都需要后续学习证据验证。
              </p>
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
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [disputeOpen, setDisputeOpen] = useState(false);
  const [disputeSubmitted, setDisputeSubmitted] = useState(false);
  const rows = useMemo(
    () =>
      profileDimensions.map(
        (item) => [item.name, `${item.score}`, item.nodes] as const,
      ),
    [],
  );

  return (
    <div className="foundation-page profile-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">GROWTH · EVIDENCE PROFILE</p>
          <h1>我的学习画像</h1>
          <p>每个分数都可追溯到知识节点与学习证据，浏览器不重新计算正式状态</p>
        </div>
        <span className="status-chip">画像版本 v3</span>
      </div>

      <div className="profile-layout">
        <ChartFrame
          columns={["能力维度", "分数", "知识节点 / 能力簇"]}
          description="八个维度按知识节点聚合，0 到 100 分；分数来自画像版本 v3。"
          rows={rows}
          title="八维能力画像"
        >
          <div className="profile-bars">
            {profileDimensions.map((item) => (
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
          <h2>画像版本 v3</h2>
          <dl>
            <div>
              <dt>生成时间</dt>
              <dd>2026-07-17 10:24</dd>
            </div>
            <div>
              <dt>规则版本</dt>
              <dd>profile-policy-1.2</dd>
            </div>
            <div>
              <dt>证据范围</dt>
              <dd>34 条已确认事件</dd>
            </div>
            <div>
              <dt>聚合方式</dt>
              <dd>按知识节点聚合</dd>
            </div>
          </dl>
          <p className="profile-rule-note">
            Agent 仅提出画像候选，正式版本由确定性规则组件写入。
          </p>
          <button
            className="profile-secondary-button"
            onClick={() => setEvidenceOpen((open) => !open)}
            type="button"
          >
            <FileMagnifyingGlass size={17} />{" "}
            {evidenceOpen ? "收起画像证据" : "查看画像证据"}
          </button>
          <button
            className="profile-secondary-button"
            onClick={() => setDisputeOpen(true)}
            type="button"
          >
            对画像提出异议
          </button>
          {disputeSubmitted ? (
            <p
              aria-label="异议状态"
              className="profile-dispute-status"
              role="status"
            >
              异议已提交 · 审核前画像版本保持不变
            </p>
          ) : null}
        </aside>
      </div>

      {evidenceOpen ? (
        <section
          aria-label="画像证据"
          className="profile-evidence"
          role="region"
        >
          <div>
            <p className="eyebrow">EVIDENCE DISCLOSURE</p>
            <h2>本版本的代表性证据</h2>
            <p>默认只展示教学摘要；证据 ID 与规则信息在此按需展开。</p>
          </div>
          <ul>
            {profileDimensions.slice(0, 4).map((item) => (
              <li id={`evidence-${item.evidence}`} key={item.evidence}>
                <span>
                  <strong>{item.name}</strong>
                  <small>{item.nodes}</small>
                </span>
                <a href={`#evidence-${item.evidence}`}>{item.evidence}</a>
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
            <p>
              请指出遗漏或错误的证据。提交后由规则与人工复核，当前画像不会被浏览器直接修改。
            </p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                setDisputeOpen(false);
                setDisputeSubmitted(true);
              }}
            >
              <label htmlFor="profile-dispute">异议说明</label>
              <textarea id="profile-dispute" minLength={8} required rows={5} />
              <div>
                <button
                  className="profile-secondary-button"
                  onClick={() => setDisputeOpen(false)}
                  type="button"
                >
                  取消
                </button>
                <button className="py-button" type="submit">
                  提交异议
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
    </div>
  );
}
