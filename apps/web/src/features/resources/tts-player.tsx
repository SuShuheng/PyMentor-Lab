import { SpeakerHigh } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { commandHeaders, configureStudentApi, safeApiMessage } from "../../student-api";
import {
  authenticatedAudioUrl,
  fetchTtsAudio,
  synthesiseSpeech,
  type TtsResponse,
  type TtsSubtitleCue,
} from "./tts-api";

/**
 * FE-019 — TTS playback UI bound to a BE-022 response.
 *
 * Design:
 * - The audio is served from an authenticated endpoint, so we fetch the bytes
 *   with the Bearer token and create a temporary blob URL for the `<audio>`
 *   element. The blob URL is revoked on unmount to avoid leaking the (private)
 *   audio in memory.
 * - Subtitle sync is driven by the `<audio>` `timeupdate` event: we map the
 *   current `currentTime` (seconds) to the cue whose `[start_ms, end_ms)`
 *   window contains it. The active cue is marked with `aria-current="true"`.
 * - Clicking a subtitle cue seeks the audio to its `start_ms`. This is the
 *   only mutation surface; the player never modifies the answer text.
 * - When `response.mock === true` we render a clear "模拟语音（无真实 TTS
 *   凭据）" label so students never mistake the stub for real TTS. The audio
 *   still plays (the backend returns a real byte stream for mock too), but
 *   the label is honest about provenance.
 */
export function TtsPlayer({
  accessToken,
  response,
}: {
  accessToken: string;
  response: TtsResponse;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [currentTimeMs, setCurrentTimeMs] = useState(0);
  const [audioSrc, setAudioSrc] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Fetch authenticated audio bytes and mint a blob URL. We intentionally do
  // this in an effect (not at render time) so the bytes are fetched once per
  // response, and the blob URL is revoked on cleanup.
  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setLoadError(null);
    fetchTtsAudio(response.audio_url, accessToken)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setAudioSrc(objectUrl);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setLoadError(
          error instanceof Error ? error.message : "无法加载讲解音频",
        );
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [accessToken, response.audio_url]);

  const activeCueIndex = useMemo(
    () => findActiveCueIndex(response.subtitle_track ?? [], currentTimeMs),
    [response.subtitle_track, currentTimeMs],
  );

  function seekToCue(cue: TtsSubtitleCue) {
    const audio = audioRef.current;
    if (!audio) return;
    // cue.start_ms → seconds. Setting currentTime is the canonical HTMLMediaElement seek.
    audio.currentTime = cue.start_ms / 1000;
    setCurrentTimeMs(cue.start_ms);
    // `play()` may be absent (jsdom) or reject (autoplay policy); either way
    // the seek already happened and the user can press play manually.
    const played = audio.play?.();
    if (played && typeof played.catch === "function") {
      played.catch(() => {
        /* non-fatal: user can press play */
      });
    }
  }

  if (loadError) {
    // Never block the answer — the parent renders the text regardless. The
    // player surfaces the failure honestly.
    return (
      <p className="tts-player-fallback" role="status">
        <SpeakerHigh size={16} /> 讲解音频暂不可用：{loadError}
      </p>
    );
  }

  return (
    <section
      aria-label="讲解音频"
      className="tts-player"
      data-testid="tts-player"
    >
      <audio
        controls
        data-testid="tts-audio"
        onTimeUpdate={(event) => {
          const seconds = event.currentTarget.currentTime;
          setCurrentTimeMs(Math.round(seconds * 1000));
        }}
        ref={audioRef}
        src={audioSrc ?? authenticatedAudioUrl(response.audio_url)}
      />
      {response.mock ? (
        <p className="tts-mock-label" role="status">
          <SpeakerHigh size={15} /> 模拟语音（无真实 TTS 凭据）
        </p>
      ) : null}
      {response.subtitle_track.length > 0 ? (
        <ol aria-label="讲解字幕" className="tts-subtitle-track">
          {(response.subtitle_track ?? []).map((cue, index) => {
            const isActive = index === activeCueIndex;
            return (
              <li
                aria-current={isActive ? "true" : undefined}
                className={`tts-subtitle${isActive ? " is-active" : ""}`}
                key={`${cue.start_ms}-${index}`}
              >
                <button
                  onClick={() => seekToCue(cue)}
                  type="button"
                >
                  <span className="tts-subtitle__time">
                    {formatTimestamp(cue.start_ms)}
                  </span>
                  <span className="tts-subtitle__text">{cue.text}</span>
                </button>
              </li>
            );
          })}
        </ol>
      ) : null}
    </section>
  );
}

/**
 * Find the cue whose `[start_ms, end_ms)` window contains `timeMs`.
 *
 * Returns -1 when no cue is active (e.g. before the first start_ms or after
 * the last end_ms). Linear scan is fine — subtitle tracks are short.
 */
export function findActiveCueIndex(
  cues: ReadonlyArray<TtsSubtitleCue>,
  timeMs: number,
): number {
  for (let index = 0; index < cues.length; index += 1) {
    const cue = cues[index];
    if (!cue) continue;
    if (timeMs >= cue.start_ms && timeMs < cue.end_ms) return index;
  }
  return -1;
}

function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}

/**
 * Orchestrator for the "播放讲解" affordance.
 *
 * Renders a button that synthesises speech for the given text via BE-022,
 * then mounts the {@link TtsPlayer}. Honours the honesty contract:
 * - Never blocks the answer. A failed POST (e.g. 503) degrades to a plain
 *   fallback note inside the narration area — the surrounding text stays.
 * - Never claims mastery or authoritative audio: mock responses are labelled
 *   by the player.
 *
 * The component owns no provider keys; it only relays the caller's access
 * token as a Bearer header.
 */
export function TtsNarration({
  accessToken,
  answerText,
  courseId,
  nodeId,
  triggerLabel = "播放讲解",
}: {
  accessToken: string;
  answerText: string;
  courseId?: string;
  nodeId?: string;
  /**
   * Optional override for the idle/retry trigger label. The tutor page uses the
   * default "播放讲解"; the oral-explanation page reuses the same orchestrator
   * but labels it "播放题目" to match its context. Default keeps FE-019
   * behaviour unchanged.
   */
  triggerLabel?: string;
}) {
  const [response, setResponse] = useState<TtsResponse | null>(null);
  const [phase, setPhase] = useState<"idle" | "loading" | "ready" | "error">(
    "idle",
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function startNarration() {
    if (!answerText.trim() || phase === "loading") return;
    setPhase("loading");
    setErrorMessage(null);
    configureStudentApi();
    const result = await synthesiseSpeech({
      body: { text: answerText, course_id: courseId, node_id: nodeId },
      headers: commandHeaders(accessToken, "tts"),
    });
    if (!result.data) {
      // Degraded path: never block the answer. The button stays available so
      // the student can retry once the provider recovers.
      setPhase("error");
      setErrorMessage(safeApiMessage(result.error));
      return;
    }
    setResponse(result.data);
    setPhase("ready");
  }

  if (phase === "idle") {
    return (
      <button
        className="tts-trigger"
        disabled={!answerText.trim()}
        onClick={startNarration}
        type="button"
      >
        <SpeakerHigh size={16} /> {triggerLabel}
      </button>
    );
  }

  if (phase === "loading") {
    return (
      <p className="tts-trigger tts-trigger--loading" role="status">
        <SpeakerHigh size={16} /> 正在合成讲解…
      </p>
    );
  }

  if (phase === "error") {
    return (
      <div className="tts-narration-fallback">
        <button className="tts-trigger" onClick={startNarration} type="button">
          <SpeakerHigh size={16} /> 重试{triggerLabel}
        </button>
        <p className="tts-player-fallback" role="status">
          <SpeakerHigh size={16} /> 讲解音频暂不可用：{errorMessage}
        </p>
      </div>
    );
  }

  // phase === "ready". The response is set in the same branch that flips the
  // phase to "ready", but TS cannot correlate the two state variables, so we
  // guard explicitly. If we ever reach here without a response, fall back to
  // the idle affordance rather than crashing.
  if (!response) {
    return (
      <button
        className="tts-trigger"
        disabled={!answerText.trim()}
        onClick={startNarration}
        type="button"
      >
        <SpeakerHigh size={16} /> {triggerLabel}
      </button>
    );
  }
  return (
    <div className="tts-narration">
      <TtsPlayer accessToken={accessToken} response={response} />
      <button
        className="tts-trigger tts-trigger--secondary"
        onClick={() => {
          setResponse(null);
          setPhase("idle");
        }}
        type="button"
      >
        收起讲解
      </button>
    </div>
  );
}
