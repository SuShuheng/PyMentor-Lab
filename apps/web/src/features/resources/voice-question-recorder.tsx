/**
 * FE-022 — voice-question recorder for the tutor page.
 *
 * A self-contained control that turns a spoken question into editable text:
 *
 *   语音提问 → (mic permission) → MediaRecorder → 停止录音并识别
 *            → BE-025 `POST /api/v1/asr` → onTranscript(transcript)
 *
 * Privacy / lifecycle contract:
 * - No raw audio is persisted client-side. The captured blob lives only long
 *   enough to be uploaded; once BE-025 returns a transcript we drop every
 *   reference (recorder, stream tracks, chunk array) so the GC can reclaim it.
 * - The component NEVER auto-submits. It hands the transcript back to the
 *   parent, which fills the existing composer textarea so the student reviews
 *   and edits before sending — identical to typing the question.
 * - Recording is hard-capped at `MAX_ASR_DURATION_MS` (60s) client-side to
 *   match BE-025; hitting the cap auto-stops and uploads, so no audio is lost.
 * - Degraded paths never block the keyboard flow:
 *     · permission denied → `语音录音失败` alert with a "use the keyboard" hint
 *     · ASR 503 / network → `语音识别不可用` alert prompting the student to type
 *
 * MediaRecorder is a browser API and is not implemented in jsdom; the unit
 * tests install a minimal double (see asr-voice-question.test.tsx). The
 * runtime guards every entry point so the component degrades to a no-op button
 * on browsers without MediaRecorder / getUserMedia instead of crashing.
 */
import { Microphone, StopCircle, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { commandHeaders } from "../../student-api";
import {
  MAX_ASR_DURATION_MS,
  submitAsr,
} from "./asr-api";

type RecorderPhase = "idle" | "requesting" | "recording" | "transcribing";

type VoiceQuestionRecorderProps = {
  /** Bearer access token for the BE-025 call. */
  accessToken: string;
  /** Disabled while the tutor stream is active (no concurrent submissions). */
  disabled?: boolean;
  /** Receives the recognised transcript; the parent fills the composer. */
  onTranscript: (transcript: string) => void;
  /**
   * Optional seam that yields the raw captured audio blob instead of running
   * the BE-025 ASR call. When provided, the recorder skips transcription and
   * hands the parent the clip (with its observed MIME) so the parent can ship
   * it to a different endpoint (e.g. FE-023 oral-explanation, which performs
   * its own ASR server-side). FE-022's default behaviour (no prop) is
   * unchanged: ASR runs and `onTranscript` receives the text.
   */
  onAudioCaptured?: (clip: Blob) => void;
  /**
   * Optional accessible label override for the idle trigger button. The tutor
   * page uses the default "语音提问"; the oral-explanation page reuses the same
   * control but labels it "开始录音" to match its context.
   */
  triggerLabel?: string;
};

/**
 * A captured chunk handed to `ondataavailable`. Typed loosely because the
 * browser's `BlobEvent` shape is environment-dependent in tests.
 */
type ChunkEvent = { data: Blob };

/**
 * The slice of the MediaRecorder surface this component relies on. Defining it
 * here (rather than referencing the global) keeps the component testable: the
 * jsdom double only needs to implement these members.
 */
interface RecorderLike {
  state: "inactive" | "recording";
  ondataavailable: ((event: ChunkEvent) => void) | null;
  onstop: (() => void) | null;
  start(): void;
  stop(): void;
}

declare global {
  interface Window {
    MediaRecorder?: new (stream: MediaStream) => RecorderLike;
  }
}

async function resolveMediaRecorder(): Promise<
  { recorder: RecorderLike; stream: MediaStream } | { error: "unsupported" | "denied" }
> {
  if (
    typeof window === "undefined" ||
    typeof window.MediaRecorder !== "function" ||
    !navigator?.mediaDevices?.getUserMedia
  ) {
    return { error: "unsupported" };
  }
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    return { error: "denied" };
  }
  return { recorder: new window.MediaRecorder(stream), stream };
}

/** Pick a MIME the recorder actually produced; fall back to webm for upload. */
function clipMimeType(actual: string | undefined): string {
  if (actual && /audio\/(wav|webm|ogg|mpeg)/i.test(actual)) return actual;
  return "audio/webm";
}

export function VoiceQuestionRecorder({
  accessToken,
  disabled = false,
  onTranscript,
  onAudioCaptured,
  triggerLabel = "语音提问",
}: VoiceQuestionRecorderProps) {
  const [phase, setPhase] = useState<RecorderPhase>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<"permission" | "unavailable" | null>(null);
  const [transcriptJustArrived, setTranscriptJustArrived] = useState(false);

  const recorderRef = useRef<RecorderLike | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const capTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const releaseCapture = useCallback(() => {
    if (capTimerRef.current !== null) {
      clearTimeout(capTimerRef.current);
      capTimerRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
    chunksRef.current = [];
  }, []);

  // Tear down any live capture if the component unmounts mid-recording.
  useEffect(() => releaseCapture, [releaseCapture]);

  const handleTranscribe = useCallback(
    async (chunks: Blob[], mime: string) => {
      const clip = new Blob(chunks, { type: clipMimeType(mime) });
      // Drop the only client-side copy of the raw chunks immediately; the clip
      // is the single reference handed downstream.
      chunksRef.current = [];

      // FE-023 seam: when the caller wants the raw audio (e.g. to ship to
      // BE-026 oral-explanation, which performs its own ASR server-side), skip
      // the BE-025 transcription call entirely and yield the clip. The parent
      // is responsible for the clip's lifecycle after this point.
      if (onAudioCaptured) {
        onAudioCaptured(clip);
        setPhase("idle");
        return;
      }

      setPhase("transcribing");
      setErrorMessage(null);
      setErrorKind(null);
      try {
        const result = await submitAsr({
          body: { file: clip },
          headers: commandHeaders(accessToken, "asr-voice"),
        });
        if (result.data?.transcript) {
          onTranscript(result.data.transcript);
          setTranscriptJustArrived(true);
          setPhase("idle");
          return;
        }
        // No transcript → degraded. A 503 (or any non-ok) means "type instead".
        setErrorKind("unavailable");
        setErrorMessage("语音识别暂不可用，请键入问题。");
        setPhase("idle");
      } catch {
        // submitAsr is typed to not throw, but defend against transport errors.
        setErrorKind("unavailable");
        setErrorMessage("语音识别暂不可用，请键入问题。");
        setPhase("idle");
      }
    },
    [accessToken, onAudioCaptured, onTranscript],
  );

  const startRecording = useCallback(async () => {
    setErrorMessage(null);
    setErrorKind(null);
    setTranscriptJustArrived(false);
    setPhase("requesting");
    const resolved = await resolveMediaRecorder();
    if ("error" in resolved) {
      setPhase("idle");
      setErrorKind("permission");
      setErrorMessage(
        resolved.error === "denied"
          ? "麦克风权限被拒绝，请允许后重试或在上方键入问题。"
          : "当前设备不支持语音录入，请在上方键入问题。",
      );
      return;
    }
    const { recorder, stream } = resolved;
    recorderRef.current = recorder;
    streamRef.current = stream;
    chunksRef.current = [];

    recorder.ondataavailable = (event: ChunkEvent) => {
      if (event.data?.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      const captured = chunksRef.current;
      const mime = (recorder as unknown as { mimeType?: string }).mimeType;
      releaseCapture();
      void handleTranscribe(captured, mime ?? "audio/webm");
    };

    recorder.start();
    setPhase("recording");
    // Client-side 60s cap matching BE-025; auto-stop so no audio is lost.
    capTimerRef.current = setTimeout(() => {
      if (recorderRef.current?.state === "recording") {
        recorderRef.current.stop();
      }
    }, MAX_ASR_DURATION_MS);
  }, [handleTranscribe, releaseCapture]);

  const stopAndTranscribe = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state !== "recording") return;
    recorder.stop();
  }, []);

  const cancelRecording = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state === "recording") {
      // Detach handlers so onstop does NOT upload — we are discarding.
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.stop();
    }
    releaseCapture();
    setPhase("idle");
  }, [releaseCapture]);

  if (phase === "idle") {
    return (
      <>
        {errorKind === "permission" && errorMessage ? (
          <p aria-label="语音录音失败" className="tutor-voice-note tutor-voice-note--error" role="alert">
            <Microphone size={15} /> {errorMessage}
          </p>
        ) : null}
        {errorKind === "unavailable" && errorMessage ? (
          <p aria-label="语音识别不可用" className="tutor-voice-note tutor-voice-note--error" role="alert">
            <Microphone size={15} /> {errorMessage}
          </p>
        ) : null}
        {transcriptJustArrived ? (
          <p aria-label="语音转写结果" className="tutor-voice-note" role="status">
            <Microphone size={15} /> 已从语音转写，可编辑后发送。
          </p>
        ) : null}
        <button
          className="tutor-voice-button"
          disabled={disabled}
          onClick={startRecording}
          type="button"
        >
          <Microphone size={16} /> {triggerLabel}
        </button>
      </>
    );
  }

  if (phase === "requesting") {
    return (
      <p aria-label="语音录音" className="tutor-voice-status" role="status">
        <Microphone size={16} /> 正在请求麦克风权限…
      </p>
    );
  }

  if (phase === "transcribing") {
    return (
      <p aria-label="语音识别中" className="tutor-voice-status" role="status">
        <Microphone size={16} /> 正在识别语音…
      </p>
    );
  }

  // phase === "recording"
  return (
    <div aria-label="语音录音" className="tutor-voice-recording" role="status">
      <span className="tutor-voice-recording__pulse" aria-hidden="true" />
      <span>录音中（最长 60 秒）</span>
      <div>
        <button onClick={stopAndTranscribe} type="button">
          <StopCircle size={16} weight="fill" />{" "}
          {onAudioCaptured ? "停止录音" : "停止录音并识别"}
        </button>
        <button className="tutor-voice-cancel" onClick={cancelRecording} type="button">
          <X size={16} /> 取消录音
        </button>
      </div>
    </div>
  );
}
