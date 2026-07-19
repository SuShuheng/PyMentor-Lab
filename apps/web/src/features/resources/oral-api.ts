/**
 * FE-023 — typed wrapper for BE-026 `POST /api/v1/oral-explanation`.
 *
 * The generated SDK (@pymentor/api-client) does not yet expose this route, so
 * we post through the shared `client` from the generated runtime and keep the
 * request/response types here — mirroring the FE-014/018/019/020/021/022
 * wrappers. When the OpenAPI generator picks the route up, this wrapper can be
 * retired in favour of the generated function without changing call sites.
 *
 * Honesty / evidence contract (BE-026):
 * - The endpoint scores a student's *oral* explanation of a concept and
 *   records an `ORAL_EXPLANATION_SCORED` evidence event. It NEVER transitions
 *   mastery; the wrapper carries the server's `evidence_id` back so the UI can
 *   tell the student the result is recorded as evidence only. The UI MUST
 *   communicate that mastery is decided server-side and is not auto-advanced.
 * - The response carries `mock: true` when the backend has no real
 *   LLM/ASR/TTS credentials. The wrapper surfaces that flag unchanged; the UI
 *   MUST label mock responses clearly and never present a stub score as real.
 * - Audio is ephemeral: the caller hands a `File`/`Blob` to
 *   `scoreOralExplanation`, it goes straight into a multipart body, and the
 *   wrapper never retains a reference to it. The UI MUST drop the captured
 *   blob as soon as the response is returned — no raw audio is persisted
 *   client-side.
 * - The MIME allowlist + size cap are enforced here, before any network call,
 *   so a hostile or buggy caller cannot push a disallowed payload. The backend
 *   re-validates; these guards are defence-in-depth and a friendlier message.
 */
import { client } from "@pymentor/api-client";

/**
 * Audio MIME types BE-026 accepts (wav / webm / ogg / mp3). Mirrors the
 * backend allowlist one-to-one (same as BE-025 ASR) so a client-side guard
 * rejects anything the server would reject anyway — with a friendlier message.
 */
export const ORAL_ACCEPTED_MIME: ReadonlySet<string> = new Set([
  "audio/wav",
  "audio/webm",
  "audio/ogg",
  "audio/mpeg",
]);

/** Hard ceiling on the uploaded audio payload (25 MiB), matching BE-026. */
export const MAX_ORAL_AUDIO_BYTES = 25 * 1024 * 1024;

/** One subtitle cue for the prompt audio (`[start_ms, end_ms)`, plain text). */
export type OralPromptSubtitleCue = {
  start_ms: number;
  end_ms: number;
  text: string;
};

/** The prompt the backend may synthesise to read the question aloud. */
export type OralPrompt = {
  /** Authenticated URL of the TTS prompt audio (served with Bearer token). */
  audio_url: string;
  /** Time-aligned subtitle cues for the prompt audio. May be empty. */
  subtitle_track: ReadonlyArray<OralPromptSubtitleCue>;
  /** `true` when the prompt audio is a stub (no real TTS credentials). */
  mock: boolean;
};

/** One rubric row returned by BE-026: a criterion, its score and feedback. */
export type OralRubricItem = {
  /** Human-readable criterion name (e.g. "准确性"). */
  criterion: string;
  /** Per-criterion score in 0..1. */
  score: number;
  /** Plain-text feedback explaining the score. May be empty. */
  feedback: string;
};

/** Request body for `POST /api/v1/oral-explanation`. */
export type OralRequest = {
  /** The knowledge node the explanation is being assessed against. */
  node_id: string;
  /** The prompt the student answered (echoed to the backend for context). */
  prompt_text: string;
  /** The captured oral-answer audio. One of {@link ORAL_ACCEPTED_MIME}. */
  audio: File | Blob;
};

/** Successful response body returned by BE-026. */
export type OralResponse = {
  /** Overall score in 0..1 (aggregate of the rubric). */
  score: number;
  /** Per-criterion breakdown. May be empty when the rubric is degenerate. */
  rubric: ReadonlyArray<OralRubricItem>;
  /** ASR transcript of the student's answer. */
  transcript: string;
  /** Reference answer the backend used to score against. */
  model_answer: string;
  /** The prompt audio (synthesised from prompt_text) the student heard. */
  prompt: OralPrompt;
  /** Server-assigned evidence id for the recorded ORAL_EXPLANATION_SCORED. */
  evidence_id: string;
  /** `true` when the backend has no real LLM/ASR/TTS credentials. */
  mock: boolean;
};

export type OralOptions = {
  body: OralRequest;
  headers: { Authorization: string; "Idempotency-Key": string };
};

type OralResult = {
  data: OralResponse | null;
  error: unknown;
  response: Response;
};

/**
 * Client-side validation result. `ok === false` carries a user-facing message
 * the UI can render verbatim.
 */
export type OralAudioValidation =
  | { ok: true }
  | { ok: false; message: string };

/**
 * Validate a candidate audio clip against the BE-026 allowlist + size cap
 * before any network call. Exported so both the wrapper and the UI can reuse
 * the exact same rule (single source of truth).
 */
export function validateOralAudio(audio: File | Blob): OralAudioValidation {
  const mime = audio.type;
  if (!ORAL_ACCEPTED_MIME.has(mime)) {
    return {
      ok: false,
      message: `不支持的音频格式：${mime || "未知"}，请使用 wav / webm / ogg / mp3。`,
    };
  }
  if (audio.size > MAX_ORAL_AUDIO_BYTES) {
    return { ok: false, message: "录音文件超过 25 MiB 上限，请缩短后重试。" };
  }
  return { ok: true };
}

/**
 * Score a student's oral explanation against a knowledge node.
 *
 * The caller MUST supply an `Idempotency-Key` (use `commandHeaders` from
 * `student-api`). Mirrors the generated SDK's `{ data, error, response }`
 * result shape so callers can branch on `response.status` for the degraded
 * path (503 → honest failure).
 *
 * Multipart note: we hand a `FormData` to the client WITHOUT a Content-Type
 * header so the platform sets the multipart boundary. Setting it manually
 * would omit the boundary and corrupt the body.
 */
export async function scoreOralExplanation({
  body,
  headers,
}: OralOptions): Promise<OralResult> {
  const validation = validateOralAudio(body.audio);
  if (!validation.ok) {
    return clientError(new Error(validation.message));
  }

  const form = new FormData();
  form.append("node_id", body.node_id);
  form.append("prompt_text", body.prompt_text);
  form.append("audio", body.audio, fileNameFor(body.audio));

  const result = await client.post<OralResponse, unknown, false>({
    body: form,
    // The client's default bodySerializer is `JSON.stringify`, which would
    // stringify the FormData into "{}" and turn the body into plain text. We
    // pass a passthrough so the FormData reaches `new Request` intact and the
    // platform sets `multipart/form-data; boundary=…` itself.
    bodySerializer: (body) => body,
    headers: {
      ...headers,
      // The client defaults to `Content-Type: application/json`. For a
      // multipart body the platform MUST set the Content-Type itself (with the
      // boundary), so we delete the default by passing `null` — the hey-api
      // client treats a null header value as a deletion.
      "Content-Type": null,
    },
    url: "/api/v1/oral-explanation",
  });

  // The hey-api client omits `data` entirely on the error branch. Normalise so
  // callers always see a stable shape: `data` is `OralResponse | null`,
  // `error` is `unknown`.
  return {
    data: result.data ?? null,
    error: result.error,
    response: result.response,
  };
}

/** `Blob` has no name; fall back to a generic clip name keyed by MIME. */
function fileNameFor(file: File | Blob): string {
  if (file instanceof File && file.name) return file.name;
  const ext = extensionFor(file.type);
  return `oral-answer.${ext}`;
}

function extensionFor(mime: string): string {
  switch (mime) {
    case "audio/wav":
      return "wav";
    case "audio/webm":
      return "webm";
    case "audio/ogg":
      return "ogg";
    case "audio/mpeg":
      return "mp3";
    default:
      return "bin";
  }
}

/**
 * Build the `{ data: null, error, response }` shape the typed wrappers return
 * for client-side validation failures, where no network call was made. We use
 * HTTP 400 (Bad Request) — a valid status within the jsdom `Response` range —
 * so callers that read `response.ok` see a coherent falsy result.
 */
function clientError(error: Error): OralResult {
  const response = new Response(null, { status: 400 });
  return { data: null, error, response };
}
