/**
 * FE-019 — typed wrapper for BE-022 TTS endpoints.
 *
 *   POST /api/v1/tts                       → synthesise speech + subtitle track
 *   GET  /api/v1/tts/audio/{rid}/{digest}  → authenticated audio bytes
 *
 * The generated SDK (@pymentor/api-client) does not yet expose these routes,
 * so we go through the shared `client` from the generated runtime and keep the
 * request/response types here — mirroring the FE-014/018/020 wrappers. When
 * the OpenAPI generator picks the routes up, this wrapper can be retired in
 * favour of the generated function without changing call sites.
 *
 * Honesty / degradation contract (BE-022):
 * - The response carries `mock: true` when the backend has no real TTS
 *   credentials. The UI MUST surface that as an explicit "模拟语音" label so
 *   students never mistake a stub for real synthesised speech.
 * - `audio_url` is served from an authenticated endpoint; the browser MUST
 *   pass the Bearer access token. We expose `authenticatedAudioUrl()` so the
 *   player can request bytes with the right header instead of relying on a
 *   public URL.
 * - If the endpoint returns 5xx (no TTS available at all), the UI MUST render
 *   the plain text answer and never block it. The wrapper surfaces the HTTP
 *   status through the standard `{ data, error, response }` shape so callers
 *   can branch on `response.status === 503`.
 */
import { client } from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";

/** One subtitle cue: `[start_ms, end_ms)` inclusive-exclusive, plain text. */
export type TtsSubtitleCue = {
  start_ms: number;
  end_ms: number;
  text: string;
};

/** Request body for `POST /api/v1/tts`. */
export type TtsRequest = {
  /** The text to synthesise — typically the tutor/micro-lecture answer. */
  text: string;
  /**
   * Optional course + node context the backend may use for voice selection.
   * Both are passed through unmodified; the UI does not interpret them.
   */
  course_id?: string;
  node_id?: string;
};

/** Successful response body returned by BE-022. */
export type TtsResponse = {
  /** Server-assigned synthesis request id (used in the audio fetch path). */
  request_id: string;
  /** SHA-style digest used as a tamper check on the audio bytes. */
  digest: string;
  /**
   * Path (relative to the API base) of the authenticated audio endpoint.
   * The UI MUST request it with the Bearer access token — see
   * `authenticatedAudioUrl()` / `fetchTtsAudio()`.
   */
  audio_url: string;
  /** Time-aligned subtitle cues. May be empty when no alignment is available. */
  subtitle_track: ReadonlyArray<TtsSubtitleCue>;
  /** MIME type of the audio bytes (e.g. `audio/mpeg`). */
  mime: string;
  /** Total audio duration in milliseconds. */
  duration_ms: number;
  /**
   * `true` when the backend has no real TTS credentials and returned a stub.
   * The UI MUST label this clearly and never present it as real audio.
   */
  mock: boolean;
};

export type TtsOptions = {
  body: TtsRequest;
  headers: { Authorization: string; "Idempotency-Key": string };
};

/**
 * Synthesise speech for a block of text.
 *
 * The caller MUST supply an `Idempotency-Key` (use `commandHeaders` from
 * `student-api`). Mirrors the generated SDK's `{ data, error, response }`
 * result shape so callers can branch on `response.status` for the degraded
 * path (503 → text-only).
 */
export async function synthesiseSpeech({ body, headers }: TtsOptions) {
  return client.post<TtsResponse, unknown, false>({
    url: "/api/v1/tts",
    body,
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
  });
}

/**
 * Resolve the audio_url against the API base. Used for the `<audio src>` hint
 * and for diagnostics; actual byte fetching still goes through `fetchTtsAudio`
 * with the Bearer header.
 */
export function authenticatedAudioUrl(audioUrl: string): string {
  if (/^https?:\/\//i.test(audioUrl)) return audioUrl;
  const base = readServerUrl().replace(/\/+$/, "");
  const path = audioUrl.startsWith("/") ? audioUrl : `/${audioUrl}`;
  return `${base}${path}`;
}

/**
 * Fetch the synthesised audio bytes with the Bearer access token.
 *
 * Returns the raw `Response` so the player can either stream it via a blob
 * URL or hand it to the platform audio stack. Callers MUST check `response.ok`
 * — a 401/403 indicates the session expired; a 5xx indicates the object is
 * unavailable.
 */
export async function fetchTtsAudio(
  audioUrl: string,
  accessToken: string,
): Promise<Response> {
  return fetch(authenticatedAudioUrl(audioUrl), {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
