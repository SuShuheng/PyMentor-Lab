/**
 * FE-021 — typed wrapper for BE-024 `POST /api/v1/ocr`.
 *
 * The generated SDK (@pymentor/api-client) does not yet expose this endpoint,
 * so we post through the shared `client` from the generated runtime and keep
 * the request/response types here — mirroring the FE-014 onboarding, FE-018
 * knowledge-graph and FE-020 practice wrappers. When the OpenAPI generator
 * picks the route up, this wrapper can be retired in favour of the generated
 * function without changing call sites.
 *
 * Honesty contract (BE-024):
 * - The endpoint accepts a single screenshot (`file` part) and returns the
 *   server-extracted text. It performs NO mastery/state mutation, so no
 *   idempotency key is strictly required by the contract; however callers
 *   SHOULD still pass one so transient retries are safe and the audit trail
 *   can correlate a screenshot to the code-run it came from.
 * - The MIME allowlist and 5 MiB cap are enforced server-side; this wrapper
 *   mirrors them client-side too so we never make the network call for a file
 *   we know will be rejected (matches the task's "client-side validation"
 *   requirement and keeps the upload UX honest — no false "uploading…" state
 *   on a file the server will refuse).
 * - `confidence` is optional on the wire; the UI degrades when absent.
 */
import { client } from "@pymentor/api-client";

/**
 * MIME types BE-024 will accept. Kept as an exported readonly set so the UI
 * can reuse it for `<input accept>` and for validation messaging, and so a
 * future generator-picked enum can replace this constant without touching
 * call sites.
 */
export const OCR_ACCEPTED_MIME: ReadonlySet<string> = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
]);

/**
 * 5 MiB hard cap, mirroring BE-024. Exported so the UI can format the same
 * number in its error message ("不得超过 5 MiB") and the validation error.
 */
export const MAX_OCR_FILE_BYTES = 5 * 1024 * 1024;

/** Successful response body returned by BE-024. */
export type OcrResponse = {
  /** Text the OCR backend extracted from the screenshot. May be empty. */
  extracted_text: string;
  /**
   * Optional model confidence in 0..1. BE-024 MAY omit this; the UI degrades
   * to showing only the extracted text in that case.
   */
  confidence?: number;
  /** Echoed MIME of the accepted part. */
  mime: string;
  /** Echoed byte length of the accepted part. */
  size_bytes: number;
};

export type OcrRequestBody = {
  /** The screenshot part. Must satisfy the MIME/size guardrails above. */
  file: File;
};

export type SubmitOcrOptions = {
  body: OcrRequestBody;
  /**
   * Caller MUST supply Bearer auth. An idempotency key is recommended but the
   * wrapper tolerates either header set — use `commandHeaders` from
   * `student-api` to get both.
   */
  headers: { Authorization: string; "Idempotency-Key"?: string };
};

/**
 * Client-side validation result. `ok === false` carries a user-facing message
 * the UI can render verbatim (it already mentions the format/size rule).
 */
export type OcrFileValidation =
  | { ok: true }
  | { ok: false; message: string };

/**
 * Validate a candidate screenshot against the BE-024 allowlist + size cap
 * before any network call. Exported so both the wrapper and the UI can reuse
 * the exact same rule (single source of truth).
 */
export function validateOcrFile(file: File): OcrFileValidation {
  if (!OCR_ACCEPTED_MIME.has(file.type)) {
    return {
      ok: false,
      message: `不支持的图片格式（${file.type || "未知"}），仅支持 PNG / JPEG / WebP。`,
    };
  }
  if (file.size > MAX_OCR_FILE_BYTES) {
    return {
      ok: false,
      message: "截图过大，不得超过 5 MiB。",
    };
  }
  return { ok: true };
}

/**
 * Result shape returned by `submitOcr`. The runtime's native shape omits
 * `data` on the error branch (it returns `{ error, response }`); we normalise
 * to an explicit `data: null` so callers can branch on a single truthy check
 * (`if (!result.data)`) without worrying about `undefined` vs `null`.
 */
export type SubmitOcrResult = {
  data: OcrResponse | null;
  error: unknown;
  response: Response;
};

/**
 * Submit a screenshot for OCR transcription.
 *
 * Builds the `multipart/form-data` body by hand (one `file` part) and lets
 * the browser set the boundary — the hey-api runtime defaults the request
 * `Content-Type` to `application/json`, so we explicitly drop it (by setting
 * the header to `null`, which the runtime's header-merger deletes) and let
 * `fetch` stamp the multipart boundary itself. Setting an explicit
 * `multipart/form-data; boundary=…` would lose the boundary on the server.
 *
 * Mirrors the generated SDK's `{ data, error, response }` result shape so
 * callers can use the same error-handling idiom as the generated endpoints.
 * On a client-side validation failure the wrapper returns the same shape
 * WITHOUT calling `client.post`, so the UI never enters a fake "uploading"
 * state for a file the server would refuse.
 */
export async function submitOcr({
  body,
  headers,
}: SubmitOcrOptions): Promise<SubmitOcrResult> {
  const validation = validateOcrFile(body.file);
  if (!validation.ok) {
    return clientFail(validation.message);
  }
  const result = await client.post<OcrResponse, unknown, false>({
    url: "/api/v1/ocr",
    body: buildMultipart(body.file),
    headers: {
      ...headers,
      // Null deletes the runtime's default `application/json` so the browser
      // sets `multipart/form-data; boundary=…` from the FormData body.
      "Content-Type": null,
    },
    // The runtime's DEFAULT config carries a `bodySerializer` that JSON-
    // stringifies every body, which would corrupt a FormData. Pass
    // `undefined` (key present, value undefined) so spread overrides the
    // default and our pre-built FormData flows straight through to
    // `new Request`, letting fetch stamp the multipart boundary.
    bodySerializer: undefined,
    // Tell the runtime to parse the response as JSON regardless of the
    // request body type.
    parseAs: "json",
  });
  return {
    data: result.data ?? null,
    error: result.error,
    response: result.response,
  };
}

function buildMultipart(file: File): FormData {
  const form = new FormData();
  form.append("file", file);
  return form;
}

/**
 * Build a `{ data: null, error }` result that matches the SDK shape WITHOUT
 * making a network call. `status: 422` is the closest honest HTTP semantic
 * for "client-side guardrail rejected the input before send"; callers only
 * read `result.data` / `result.error` (the codebase idiom), and
 * `safeApiMessage` reads `error.message` for the user-facing string.
 */
function clientFail(message: string): SubmitOcrResult {
  return {
    data: null,
    error: new Error(message),
    response: new Response(null, { status: 422 }),
  };
}
