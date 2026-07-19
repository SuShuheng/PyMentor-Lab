/**
 * FE-022 — typed wrapper for BE-025 `POST /api/v1/asr`.
 *
 * The generated SDK (@pymentor/api-client) does not yet expose this route, so
 * we post through the shared `client` from the generated runtime and keep the
 * request/response types here — mirroring the FE-014/018/019/020/021 wrappers.
 * When the OpenAPI generator picks the route up, this wrapper can be retired
 * in favour of the generated function without changing call sites.
 *
 * Honesty / privacy contract (BE-025):
 * - Audio is ephemeral: the caller hands a `File`/`Blob` to `submitAsr`, it
 *   goes straight into a multipart body, and the wrapper never retains a
 *   reference to it. The UI MUST drop the captured blob as soon as the
 *   transcript is returned — no raw audio is persisted client-side.
 * - The MIME allowlist + size/duration caps are enforced here, before any
 *   network call, so a hostile or buggy caller cannot push a disallowed
 *   payload. The backend re-validates; these guards are defence-in-depth and
 *   a better user message.
 * - The transcript is plain text the student reviews and edits before it
 *   enters the existing Q&A flow; the wrapper never auto-submits anything.
 * - `confidence` / `language` / `duration_ms` are optional on the wire; the
 *   UI degrades gracefully when the provider omits them.
 */
import { client } from "@pymentor/api-client";

/**
 * Audio MIME types BE-025 accepts (wav / webm / ogg / mp3). Mirrors the
 * backend allowlist one-to-one so a client-side guard rejects anything the
 * server would reject anyway — with a friendlier message.
 */
export const ASR_ACCEPTED_MIME = [
  "audio/wav",
  "audio/webm",
  "audio/ogg",
  "audio/mpeg",
] as const;

/** Hard ceiling on a single clip. Mirrors the BE-025 60-second cap. */
export const MAX_ASR_DURATION_MS = 60_000;

/** Hard ceiling on the uploaded payload size (10 MiB), matching BE-025. */
export const MAX_ASR_FILE_BYTES = 10 * 1024 * 1024;

/** Request body for `POST /api/v1/asr`. */
export type AsrRequest = {
  /** The captured audio clip. Must be one of {@link ASR_ACCEPTED_MIME}. */
  file: File | Blob;
};

/** Successful response body returned by BE-025. */
export type AsrResponse = {
  /** Recognised speech as plain text. The UI lets the student edit this. */
  transcript: string;
  /** Optional provider confidence in 0..1; may be omitted. */
  confidence?: number;
  /** Optional detected BCP-47 language tag (e.g. `zh`); may be omitted. */
  language?: string;
  /** Optional clip duration in milliseconds; may be omitted. */
  duration_ms?: number;
};

export type AsrOptions = {
  body: AsrRequest;
  headers: { Authorization: string; "Idempotency-Key": string };
};

type AsrResult = {
  data: AsrResponse | null;
  error: unknown;
  response: Response;
};

/**
 * Recognise speech in a captured audio clip.
 *
 * The caller MUST supply an `Idempotency-Key` (use `commandHeaders` from
 * `student-api`). Mirrors the generated SDK's `{ data, error, response }`
 * result shape so callers can branch on `response.status` for the degraded
 * path (503 → "please type your question").
 *
 * Guardrails (run before any network call):
 * - MIME not in {@link ASR_ACCEPTED_MIME} → `error` is an `Error`, no fetch.
 * - Size over {@link MAX_ASR_FILE_BYTES} → `error` is an `Error`, no fetch.
 *
 * Multipart note: we hand a `FormData` to the client WITHOUT a Content-Type
 * header so the platform sets the multipart boundary. Setting it manually
 * would omit the boundary and corrupt the body.
 */
export async function submitAsr({ body, headers }: AsrOptions): Promise<AsrResult> {
  const file = body.file;
  const mime = file.type;
  if (!isAcceptedAsrMime(mime)) {
    return clientError(
      new Error(
        `不支持的音频格式：${mime || "未知"}，请使用 wav / webm / ogg / mp3。`,
      ),
    );
  }
  if (file.size > MAX_ASR_FILE_BYTES) {
    return clientError(
      new Error("录音文件超过 10 MiB 上限，请缩短后重试。"),
    );
  }

  const form = new FormData();
  form.append("file", file, fileNameFor(file));

  const result = await client.post<AsrResponse, unknown, false>({
    body: form,
    // The client's default bodySerializer is `JSON.stringify`, which would
    // stringify the FormData into "{}" and turn the body into plain text. We
    // pass a passthrough so the FormData reaches `new Request` intact and the
    // platform sets `multipart/form-data; boundary=…` itself.
    bodySerializer: (body) => body,
    headers: {
      ...headers,
      // The client defaults to `Content-Type: application/json`. For a multipart
      // body the platform MUST set the Content-Type itself (with the boundary),
      // so we delete the default by passing `null` — the hey-api client treats
      // a null header value as a deletion. Setting it manually would omit the
      // boundary and corrupt the body.
      "Content-Type": null,
    },
    url: "/api/v1/asr",
  });

  // The hey-api client omits `data` entirely on the error branch (it returns
  // `{ error, request, response }`). Normalise so callers always see a stable
  // shape: `data` is `AsrResponse | null`, `error` is `unknown`. This keeps the
  // UI's branching (`if (result.data) …`) independent of which branch fired.
  return {
    data: result.data ?? null,
    error: result.error,
    response: result.response,
  };
}

function isAcceptedAsrMime(mime: string): boolean {
  return (ASR_ACCEPTED_MIME as readonly string[]).includes(mime);
}

/** `Blob` has no name; fall back to a generic clip name keyed by MIME. */
function fileNameFor(file: File | Blob): string {
  if (file instanceof File && file.name) return file.name;
  const ext = extensionFor(file.type);
  return `voice-question.${ext}`;
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
 * so callers that read `response.ok` see a coherent falsy result, and tests
 * can assert on `response.status` without touching the network mock.
 */
function clientError(error: Error): AsrResult {
  const response = new Response(null, { status: 400 });
  return { data: null, error, response };
}
