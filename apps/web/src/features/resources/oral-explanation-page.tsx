/**
 * FE-023 — Oral explanation scoring page (BE-026).
 *
 * The student verbally explains a concept; BE-026 scores the recording. This
 * page wires the two existing media components into that flow:
 *
 *   FE-019 TtsNarration   → plays the prompt (synthesised from prompt_text)
 *   FE-022 VoiceQuestionRecorder → captures the student's spoken answer
 *   BE-026 POST /api/v1/oral-explanation → scores the recording
 *
 * Honesty / evidence contract (BE-026, design §8.3):
 * - The score is recorded as an `ORAL_EXPLANATION_SCORED` evidence event and
 *   projects an INDEPENDENCE/EXPLANATION signal. It NEVER transitions mastery.
 *   The page communicates this explicitly in BOTH the pre-record and
 *   post-result states: "掌握度由系统综合判定，不会仅因本次评分而自动提升".
 * - When `response.mock === true` the page renders a clear "模拟评分（无真实
 *   LLM/ASR/TTS 凭据）" label so students never mistake a stub for a real
 *   score.
 * - The captured audio is ephemeral: it lives only long enough to be uploaded;
 *   once BE-026 returns we drop the reference. No raw audio is persisted
 *   client-side.
 *
 * Reuse over duplication: the prompt playback reuses the FE-019 TtsNarration
 * orchestrator (which owns the BE-022 synthesis + TtsPlayer mount); the answer
 * capture reuses the FE-022 VoiceQuestionRecorder via its `onAudioCaptured`
 * seam. This page owns only the BE-026 submit + result rendering.
 */
import { ArrowClockwise, Lock, Microphone, Sparkle, SpeakerHigh } from "@phosphor-icons/react";
import { StatePanel } from "@pymentor/ui";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  commandHeaders,
  configureStudentApi,
  safeApiMessage,
} from "../../student-api";
import { useAuth } from "../auth/auth-session";
import {
  scoreOralExplanation,
  type OralResponse,
} from "./oral-api";
import { TtsNarration } from "./tts-player";
import { VoiceQuestionRecorder } from "./voice-question-recorder";

type Phase = "ready" | "submitting" | "scored" | "error";

/**
 * Default prompt for a node when the caller did not supply one. In production
 * the node's prompt is sourced from the learning path / resource metadata; the
 * page falls back to a generic per-node question so the flow is always usable.
 */
function defaultPromptForNode(nodeId: string): string {
  return `请用自己的话解释节点 ${nodeId.slice(0, 8)} 中的核心概念，并举例说明。`;
}

export function OralExplanationPage() {
  const { session } = useAuth();
  const { nodeId = "" } = useParams<{ nodeId: string }>();
  const accessToken = session?.accessToken;

  const promptText = defaultPromptForNode(nodeId);
  const [clip, setClip] = useState<Blob | null>(null);
  const [phase, setPhase] = useState<Phase>("ready");
  const [result, setResult] = useState<OralResponse | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  if (!accessToken) {
    return (
      <StatePanel
        actionLabel="重新登录"
        description="登录会话缺少访问令牌，请重新登录后再进行口述评分。"
        onAction={() => undefined}
        state="error"
        title="无法进行口述评分"
      />
    );
  }

  async function handleSubmit(audio: Blob) {
    if (!accessToken || !nodeId) return;
    setPhase("submitting");
    setSubmitError(null);
    configureStudentApi();
    const response = await scoreOralExplanation({
      body: { node_id: nodeId, prompt_text: promptText, audio },
      headers: commandHeaders(accessToken, "oral-explanation"),
    });
    // Drop the only client-side copy of the audio immediately; the wrapper has
    // already handed it to fetch and we never need it again.
    setClip(null);
    if (!response.data) {
      setPhase("error");
      setSubmitError(safeApiMessage(response.error));
      return;
    }
    setResult(response.data);
    setPhase("scored");
  }

  return (
    <div className="foundation-page oral-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">ORAL EXPLANATION · BE-026</p>
          <h1>口述概念解释</h1>
          <p>
            听完题目后，用自己的话口头解释这个概念。系统会录音评分，并把结果作为学习证据记录。
          </p>
        </div>
        <Link className="profile-secondary-button" to="/map">
          返回学习地图
        </Link>
      </div>

      <section aria-labelledby="oral-prompt-title" className="oral-prompt">
        <div className="section-heading-row">
          <div>
            <p className="eyebrow">PROMPT</p>
            <h2 id="oral-prompt-title">口述题目</h2>
          </div>
          <span className="status-chip">
            <Sparkle size={16} weight="fill" /> 节点 {nodeId.slice(0, 8)}
          </span>
        </div>
        {/* The outer section is the named region (via aria-labelledby on the
            h2 above); this block just renders the prompt text + the play
            affordance. No redundant aria-label, to avoid a duplicate region. */}
        <div className="oral-prompt__text">
          <p>{promptText}</p>
          {/* FE-019 reuse: synthesise + play the prompt via TtsNarration, which
              owns the BE-022 call and the TtsPlayer mount. The trigger label is
              overridden to "播放题目" to match the oral-explanation context. */}
          <div className="oral-prompt__play">
            <TtsNarration
              accessToken={accessToken}
              answerText={promptText}
              nodeId={nodeId}
              triggerLabel="播放题目"
            />
          </div>
        </div>
      </section>

      <section aria-labelledby="oral-answer-title" className="oral-answer">
        <div className="section-heading-row">
          <div>
            <p className="eyebrow">YOUR ANSWER</p>
            <h2 id="oral-answer-title">录下你的口述回答</h2>
          </div>
          {clip ? (
            <span className="status-chip">
              <Microphone size={16} /> 已录音（{Math.max(1, Math.round(clip.size / 1024))} KB）
            </span>
          ) : null}
        </div>

        {/* FE-022 reuse: capture the spoken answer via VoiceQuestionRecorder.
            The onAudioCaptured seam makes the recorder yield the raw clip
            instead of running BE-025 ASR — BE-026 performs its own ASR. */}
        <VoiceQuestionRecorder
          accessToken={accessToken}
          disabled={phase === "submitting"}
          onAudioCaptured={(captured) => {
            setClip(captured);
            void handleSubmit(captured);
          }}
          onTranscript={() => {
            /* Unused on this page: onAudioCaptured short-circuits ASR. Kept to
               satisfy the recorder's required-prop contract. */
          }}
          triggerLabel="开始录音"
        />

        {/* The mastery-not-advanced note is shown in BOTH states so the
            contract is communicated before the student records and again after
            the result lands. Pre-record copy is forward-looking (nothing is
            recorded yet); the post-result confirmation (OralResultView) uses
            "已记录". Both communicate that oral evidence NEVER auto-advances
            mastery. */}
        <p className="oral-honesty-note" role="status">
          <Lock size={15} /> 口述评分将作为学习证据记录；掌握度由系统综合判定，不会仅因本次评分而自动提升。
        </p>

        {submitError && phase === "error" ? (
          <div className="oral-error-block">
            <p aria-label="口述评分失败" className="profile-dispute-status" role="alert">
              {submitError}
            </p>
            <button
              className="profile-secondary-button"
              onClick={() => {
                setResult(null);
                setSubmitError(null);
                setClip(null);
                setPhase("ready");
              }}
              type="button"
            >
              <ArrowClockwise size={16} /> 重新口述
            </button>
          </div>
        ) : null}
      </section>

      {phase === "submitting" ? (
        <StatePanel
          description="正在提交录音并评分（含 ASR 转写与评分模型）"
          state="loading"
          title="评分中"
        />
      ) : null}

      {phase === "scored" && result ? (
        <OralResultView
          onRetry={() => {
            setResult(null);
            setSubmitError(null);
            setClip(null);
            setPhase("ready");
          }}
          result={result}
        />
      ) : null}
    </div>
  );
}

function OralResultView({
  onRetry,
  result,
}: {
  onRetry: () => void;
  result: OralResponse;
}) {
  // 0..1 → 0..100 for display. Rounded; the contract carries the precise 0..1.
  const scorePercent = Math.round(result.score * 100);
  return (
    <section aria-label="口述评分" className="oral-result">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">SCORE · BE-026</p>
          <h2>口述评分结果</h2>
        </div>
        <span className="status-chip">
          <Sparkle size={16} weight="fill" /> 得分 {scorePercent} / 100
        </span>
      </div>

      {result.mock ? (
        <p className="oral-mock-label" role="status">
          <SpeakerHigh size={15} /> 模拟评分（无真实 LLM/ASR/TTS 凭据）
        </p>
      ) : null}

      {result.rubric.length > 0 ? (
        <ol aria-label="评分细则" className="oral-rubric">
          {result.rubric.map((item, index) => (
            <li className="oral-rubric__item" key={`${item.criterion}-${index}`}>
              <div className="oral-rubric__head">
                <strong>{item.criterion}</strong>
                <span>{Math.round(item.score * 100)} / 100</span>
              </div>
              <p>{item.feedback?.trim() ? item.feedback : "—"}</p>
            </li>
          ))}
        </ol>
      ) : null}

      <div className="oral-result__columns">
        <section aria-label="你的回答转写" className="oral-transcript">
          <p className="eyebrow">TRANSCRIPT</p>
          <p>{result.transcript?.trim() ? result.transcript : "（无转写内容）"}</p>
        </section>
        <section aria-label="参考答案" className="oral-model-answer">
          <p className="eyebrow">MODEL ANSWER</p>
          <p>{result.model_answer?.trim() ? result.model_answer : "—"}</p>
        </section>
      </div>

      <p className="oral-evidence-note">
        <Lock size={15} /> 已记录为学习证据（evidence_id {result.evidence_id}）；掌握度由系统综合判定，不会仅因本次评分而自动提升。
      </p>

      <div className="oral-actions">
        <button
          className="py-button"
          onClick={onRetry}
          type="button"
        >
          <ArrowClockwise size={16} /> 再练一次
        </button>
        <Link className="profile-secondary-button" to="/map">
          返回学习地图
        </Link>
      </div>
    </section>
  );
}
