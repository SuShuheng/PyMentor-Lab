import { ArrowClockwise, ArrowRight, CheckCircle, Sparkle, XCircle } from "@phosphor-icons/react";
import { StatePanel } from "@pymentor/ui";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  commandHeaders,
  configureStudentApi,
  safeApiMessage,
  studentAuthorization,
} from "../../student-api";
import { useAuth } from "../auth/auth-session";
import {
  getNodePracticeQuestions,
  submitPracticeAttempt,
  type PracticeAttemptResponse,
  type PracticeQuestion,
} from "./practice-api";

/**
 * FE-020 — Student self-test loop on BE-023.
 *
 * Design decisions (see task):
 * - All-at-once layout: the contract submits a single `answers: [...]` batch
 *   under one idempotency key, so we render every question on one page with
 *   radio inputs and a single submit. This is cleaner than a pager for
 *   multiple-choice self-test and keeps the per-question review side-by-side.
 * - Honesty contract: the questions endpoint returns NO answer key (the typed
 *   `PracticeQuestion` deliberately omits `answer_schema`). We never claim
 *   mastery is advanced — we render an explicit note that the result is
 *   recorded as evidence and mastery is decided server-side.
 * - CODE_WRITING-only nodes (HTTP 422 from BE-023) get an honest redirect to
 *   the code lab instead of a fake empty form.
 * - Retry ("再练一次") clears state and the next submit mints a fresh
 *   idempotency key so the server records a new evidence event.
 */
type Phase = "loading" | "form" | "submitting" | "result";

export function PracticePage() {
  const { session } = useAuth();
  const { nodeId = "" } = useParams<{ nodeId: string }>();

  const [questions, setQuestions] = useState<ReadonlyArray<PracticeQuestion> | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  // Answers keyed by question_id. Empty string = no selection yet.
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<PracticeAttemptResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // True when BE-023 returns 422 for a CODE_WRITING-only node.
  const [codeWritingOnly, setCodeWritingOnly] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!nodeId) return;
    const accessToken = session?.accessToken;
    if (!accessToken) {
      setLoadError("登录会话缺少访问令牌，请重新登录");
      setPhase("loading");
      return;
    }
    let active = true;
    configureStudentApi();
    setPhase("loading");
    setCodeWritingOnly(false);
    setLoadError(null);
    void getNodePracticeQuestions({
      nodeId,
      headers: studentAuthorization(accessToken),
    })
      .then((res) => {
        if (!active) return;
        if (res.response.status === 422) {
          // BE-023: node only supports CODE_WRITING self-test.
          setCodeWritingOnly(true);
          setPhase("loading");
          return;
        }
        if (!res.data) throw new Error(safeApiMessage(res.error));
        setQuestions(res.data);
        setAnswers({});
        setPhase("form");
      })
      .catch((error: unknown) => {
        if (active) {
          setLoadError(safeApiMessage(error));
          setPhase("loading");
        }
      });
    return () => {
      active = false;
    };
  }, [nodeId, session?.accessToken]);

  const answeredCount = useMemo(
    () => questions?.filter((q) => answers[q.question_id]?.trim()).length ?? 0,
    [questions, answers],
  );
  const allAnswered = questions ? answeredCount === questions.length : false;

  if (codeWritingOnly) {
    return (
      <div className="foundation-page practice-page">
        <section className="learning-map-empty">
          <StatePanel
            description="本节点练习通过代码实验完成。选择型自测仅覆盖 MULTIPLE_CHOICE 题型；代码写作题请在代码实验中提交。"
            state="empty"
            title="本节点通过代码实验练习"
          />
          <Link className="py-button learning-map-empty__cta" to="/lab">
            前往代码实验
          </Link>
        </section>
      </div>
    );
  }

  if (loadError) {
    return (
      <StatePanel
        actionLabel="重试"
        description={loadError}
        onAction={() => window.location.reload()}
        state="error"
        title="无法加载节点自测"
      />
    );
  }

  if (phase === "loading" && !questions) {
    return (
      <StatePanel description="正在读取本节点的 MULTIPLE_CHOICE 自测题" state="loading" title="加载节点自测" />
    );
  }

  if (!questions || questions.length === 0) {
    return (
      <section className="learning-map-empty">
        <StatePanel
          description="该节点暂未发布选择型自测题；可前往代码实验完成练习。"
          state="empty"
          title="暂无可自测题目"
        />
      </section>
    );
  }

  if (phase === "result" && result) {
    return (
      <PracticeResultView
        evidenceId={result.evidence_id}
        onRetry={() => {
          setResult(null);
          setSubmitError(null);
          setAnswers({});
          setPhase("form");
        }}
        questions={questions}
        result={result}
      />
    );
  }

  return (
    <div className="foundation-page practice-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">SELF-TEST · MULTIPLE_CHOICE</p>
          <h1>节点自测</h1>
          <p>
            选择型自测用于快速回顾；结果会作为学习证据记录，掌握度由系统综合判定。
          </p>
        </div>
        <span className="status-chip">
          <Sparkle size={16} weight="fill" /> {answeredCount}/{questions.length} 题已答
        </span>
      </div>

      <ol aria-label="自测题目" className="practice-question-list">
        {questions.map((question, index) => {
          const selected = answers[question.question_id] ?? "";
          const perQuestion = result?.per_question.find(
            (item) => item.question_id === question.question_id,
          );
          return (
            <li
              aria-label={`第 ${index + 1} 题`}
              className="practice-question"
              key={question.question_id}
            >
              <p className="eyebrow">第 {index + 1} 题 · MULTIPLE_CHOICE</p>
              <fieldset
                aria-label={question.prompt}
                className="practice-options"
                disabled={phase === "submitting"}
              >
                <legend className="practice-options__prompt">{question.prompt}</legend>
                <div className="practice-options__group" role="radiogroup" aria-label={question.prompt}>
                  {question.options.map((option) => {
                    const optionId = `${question.question_id}::${option}`;
                    return (
                      <label
                        className={`practice-option${
                          selected === option ? " is-selected" : ""
                        }`}
                        key={optionId}
                      >
                        <input
                          aria-label={option}
                          checked={selected === option}
                          name={question.question_id}
                          onChange={() =>
                            setAnswers((current) => ({
                              ...current,
                              [question.question_id]: option,
                            }))
                          }
                          type="radio"
                          value={option}
                        />
                        <span>{option}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
              {perQuestion ? (
                <p
                  aria-label="题目解析"
                  className={`practice-explanation${
                    perQuestion.correct ? " is-correct" : " is-incorrect"
                  }`}
                >
                  {perQuestion.correct ? <CheckCircle size={16} weight="fill" /> : <XCircle size={16} weight="fill" />}
                  {perQuestion.explanation?.trim() ? perQuestion.explanation : "—"}
                </p>
              ) : null}
            </li>
          );
        })}
      </ol>

      {submitError ? (
        <p aria-label="提交错误" className="profile-dispute-status" role="alert">
          {submitError}
        </p>
      ) : null}

      <div className="practice-actions">
        <button
          className="py-button"
          disabled={!allAnswered || phase === "submitting"}
          onClick={async () => {
            const accessToken = session?.accessToken;
            if (!accessToken) {
              setSubmitError("登录会话已失效，请重新登录后再提交");
              return;
            }
            setPhase("submitting");
            setSubmitError(null);
            configureStudentApi();
            const response = await submitPracticeAttempt({
              body: {
                node_id: nodeId,
                answers: questions.map((q) => ({
                  question_id: q.question_id,
                  selected_answer: answers[q.question_id] ?? "",
                })),
              },
              headers: commandHeaders(accessToken, "practice-attempt"),
            });
            if (!response.data) {
              setPhase("form");
              setSubmitError(safeApiMessage(response.error));
              return;
            }
            setResult(response.data);
            setPhase("result");
          }}
          type="button"
        >
          {phase === "submitting" ? "提交中…" : "提交自测"}{" "}
          {phase === "submitting" ? null : <ArrowRight size={16} />}
        </button>
        <p className="practice-honesty-note">
          提交后结果会作为学习证据记录（evidence_id 由服务端返回）；本次自测不会直接修改掌握度。
        </p>
      </div>
    </div>
  );
}

function PracticeResultView({
  evidenceId,
  onRetry,
  questions,
  result,
}: {
  evidenceId: string;
  onRetry: () => void;
  questions: ReadonlyArray<PracticeQuestion>;
  result: PracticeAttemptResponse;
}) {
  const percent = Math.round(result.score * 100);
  return (
    <div className="foundation-page practice-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">SELF-TEST RESULT</p>
          <h1>自测结果</h1>
          <p>已记录为学习证据；掌握度由系统综合判定，不会仅因本次通过而自动提升。</p>
        </div>
        <span className="status-chip">
          <CheckCircle size={16} weight="fill" /> 证据 {evidenceId}
        </span>
      </div>

      <section aria-label="自测结果" className="practice-score" role="status">
        <div>
          <span>本次得分</span>
          <strong>{percent}%</strong>
        </div>
        <div>
          <span>题数</span>
          <strong>{result.correct_count} / {result.total_count} 题正确</strong>
        </div>
      </section>

      <ol aria-label="题目回顾" className="practice-question-list">
        {questions.map((question, index) => {
          const perQuestion = result.per_question.find(
            (item) => item.question_id === question.question_id,
          );
          const correct = perQuestion?.correct ?? false;
          const explanation = perQuestion?.explanation?.trim()
            ? perQuestion.explanation
            : null;
          return (
            <li
              aria-label={`第 ${index + 1} 题回顾`}
              className={`practice-question practice-question--review${
                correct ? " is-correct" : " is-incorrect"
              }`}
              key={question.question_id}
            >
              <p className="eyebrow">
                第 {index + 1} 题 · {correct ? "正确" : "错误"}
              </p>
              <h3 className="practice-options__prompt">{question.prompt}</h3>
              <p
                aria-label="题目解析"
                className={`practice-explanation${correct ? " is-correct" : " is-incorrect"}`}
              >
                {correct ? <CheckCircle size={16} weight="fill" /> : <XCircle size={16} weight="fill" />}
                {explanation ?? "—"}
              </p>
            </li>
          );
        })}
      </ol>

      <p className="practice-honesty-note">
        证据编号 {evidenceId}；掌握状态由证据与规则引擎写入，不因单次自测而即时变更。
      </p>

      <div className="practice-actions">
        <button className="py-button" onClick={onRetry} type="button">
          <ArrowClockwise size={16} /> 再练一次
        </button>
        <Link className="profile-secondary-button" to="/map">
          返回学习地图
        </Link>
      </div>
    </div>
  );
}
