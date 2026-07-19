/**
 * FE-021 — error-screenshot OCR upload widget for the notebook.
 *
 * Design (see task):
 * - File pick via a hidden `<input type="file">` (paste/drag are deliberately
 *   NOT wired here — the notebook textarea already owns keyboard focus and a
 *   global paste handler would steal screenshots the student meant to paste
 *   into code; drag/drop adds layout complexity without clear value for a
 *   single-shot error capture). The input accepts only the BE-024 allowlist.
 * - Client-side validation reuses `validateOcrFile` from `ocr-api` so the UI
 *   and the wrapper share one source of truth for the MIME/size rule. An
 *   invalid file never enters the "uploading" state.
 * - Inline transcription: on success we render `extracted_text` in a callout
 *   the student can feed back into the hint flow. `confidence` is optional
 *   and only shown when present.
 * - Degraded UX mirrors the task spec: HTTP 503 → "截图识别暂不可用，请直接
 *   复制错误信息"; any other failure → a retryable error with a fresh
 *   idempotency key (BE-024 is stateless, but the key keeps the audit trail
 *   honest and lets the platform de-dupe accidental double-submits).
 * - Offline / network throw → same retry branch (the queueing the task
 *   mentions is handled implicitly: the student can retry once back online;
 *   we don't persist a queue in V1.1).
 */
import { Camera, ArrowClockwise, WarningCircle, Sparkle } from "@phosphor-icons/react";
import { useRef, useState } from "react";

import {
  commandHeaders,
  configureStudentApi,
  safeApiMessage,
} from "../../student-api";
import {
  MAX_OCR_FILE_BYTES,
  OCR_ACCEPTED_MIME,
  submitOcr,
  validateOcrFile,
  type OcrResponse,
} from "./ocr-api";

const ACCEPT_ATTR = [...OCR_ACCEPTED_MIME].join(",");

type UploadPhase =
  | { kind: "idle" }
  | { kind: "uploading" }
  | { kind: "success"; result: OcrResponse }
  | { kind: "unavailable" }
  | { kind: "error"; message: string; file: File | null };

export type OcrScreenshotUploadProps = {
  /** Student access token from the auth session. */
  accessToken: string | undefined;
};

export function OcrScreenshotUpload({ accessToken }: OcrScreenshotUploadProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<UploadPhase>({ kind: "idle" });
  const inputRef = useRef<HTMLInputElement>(null);

  function onPick(event: React.ChangeEvent<HTMLInputElement>): void {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";
    if (!file) return;
    setSelectedFile(file);
    // Surface validation immediately but don't auto-upload — let the student
    // confirm by clicking 上传截图报错.
    const check = validateOcrFile(file);
    if (!check.ok) {
      setPhase({ kind: "error", message: check.message, file });
      return;
    }
    setPhase({ kind: "idle" });
  }

  async function upload(): Promise<void> {
    if (!selectedFile) {
      setPhase({
        kind: "error",
        message: "请先选择一张错误截图。",
        file: null,
      });
      return;
    }
    const check = validateOcrFile(selectedFile);
    if (!check.ok) {
      setPhase({ kind: "error", message: check.message, file: selectedFile });
      return;
    }
    if (!accessToken) {
      setPhase({
        kind: "error",
        message: "登录会话已失效，请重新登录后再上传截图。",
        file: selectedFile,
      });
      return;
    }
    setPhase({ kind: "uploading" });
    configureStudentApi();
    const result = await submitOcr({
      body: { file: selectedFile },
      // A fresh key per click → retries mint a new evidence correlation.
      headers: commandHeaders(accessToken, "ocr-screenshot"),
    });
    if (result.data) {
      setPhase({ kind: "success", result: result.data });
      return;
    }
    if (result.response.status === 503) {
      setPhase({ kind: "unavailable" });
      return;
    }
    setPhase({
      kind: "error",
      message: safeApiMessage(result.error),
      file: selectedFile,
    });
  }

  return (
    <section
      aria-labelledby="ocr-upload-title"
      className="notebook-ocr-upload"
    >
      <div className="notebook-ocr-upload__heading">
        <Camera size={18} />
        <div>
          <h2 id="ocr-upload-title">截图报错</h2>
          <p>
            上传错误截图（PNG / JPEG / WebP，不超过 5 MiB），系统将提取文字方便你求助提示。
          </p>
        </div>
      </div>

      <div className="notebook-ocr-upload__controls">
        <input
          accept={ACCEPT_ATTR}
          aria-label="选择错误截图"
          className="notebook-ocr-upload__input"
          onChange={onPick}
          ref={inputRef}
          type="file"
        />
        <button
          className="notebook-ocr-upload__button"
          disabled={phase.kind === "uploading"}
          onClick={() => void upload()}
          type="button"
        >
          {phase.kind === "uploading" ? "识别中…" : "上传截图报错"}
        </button>
        {selectedFile && phase.kind !== "success" ? (
          <span className="notebook-ocr-upload__filename">
            已选择：{selectedFile.name}
          </span>
        ) : null}
      </div>

      {phase.kind === "success" ? (
        <div
          aria-label="截图识别结果"
          className="notebook-ocr-upload__result"
          role="status"
        >
          <div className="notebook-ocr-upload__result-head">
            <Sparkle size={16} weight="fill" />
            <span>识别到的错误信息</span>
            {typeof phase.result.confidence === "number" ? (
              <small>
                置信度 {Math.round(phase.result.confidence * 100)}%
              </small>
            ) : null}
          </div>
          <pre>{phase.result.extracted_text || "（未识别到文本）"}</pre>
          <p className="notebook-ocr-upload__hint">
            可复制以上文字，配合“分层提示”向系统求助。
          </p>
        </div>
      ) : null}

      {phase.kind === "unavailable" ? (
        <div
          aria-label="截图识别不可用"
          className="notebook-ocr-upload__unavailable"
          role="status"
        >
          <WarningCircle size={16} />
          <p>截图识别暂不可用，请直接复制错误信息并粘贴到提示求助中。</p>
        </div>
      ) : null}

      {phase.kind === "error" ? (
        <div
          aria-label="截图上传失败"
          className="notebook-ocr-upload__error"
          role="alert"
        >
          <WarningCircle size={16} />
          <p>{phase.message}</p>
          <button
            className="notebook-ocr-upload__retry"
            onClick={() => void upload()}
            type="button"
          >
            <ArrowClockwise size={14} /> 重试识别
          </button>
        </div>
      ) : null}
    </section>
  );
}

// Re-export so callers can format the cap identically without importing the
// API module directly.
export { MAX_OCR_FILE_BYTES };
