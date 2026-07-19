/**
 * FE-022 — Red tests for the ASR typed wrapper (BE-025 `POST /api/v1/asr`).
 *
 * These mirror the FE-021 OCR wrapper tests: stub `fetch`, assert the wire
 * shape (multipart, MIME/size guardrails, Bearer auth) and the typed
 * `{ data, error, response }` result shape. The transcript is later fed into
 * the existing tutor Q&A flow as a typed question — the wrapper never keeps
 * the audio blob around.
 */
import { saveServerUrl } from "@pymentor/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { commandHeaders, configureStudentApi } from "../../student-api";
import {
  ASR_ACCEPTED_MIME,
  MAX_ASR_DURATION_MS,
  MAX_ASR_FILE_BYTES,
  submitAsr,
} from "./asr-api";

function asrJson(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  window.localStorage.clear();
  saveServerUrl("https://api.example.test");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  configureStudentApi();
});

afterEach(() => vi.unstubAllGlobals());

function audioFile(bytes = 0x100, type = "audio/webm"): File {
  // 256-byte audio-ish blob; the wrapper only inspects type/size, not bytes.
  return new File([new Uint8Array(bytes)], "question.webm", { type });
}

/** Safely stringify an `unknown` error's message for assertion substrings. */
function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

describe("FE-022 asr-api submitAsr", () => {
  it("POSTs multipart/form-data to /api/v1/asr with Bearer + idempotency key and returns transcript", async () => {
    fetchMock.mockResolvedValueOnce(
      asrJson({
        transcript: "为什么 range 不包含右端点？",
        confidence: 0.93,
        language: "zh",
        duration_ms: 4200,
      }),
    );
    const file = audioFile();
    const result = await submitAsr({
      body: { file },
      headers: commandHeaders("student-access", "asr-voice"),
    });

    expect(result.response.status).toBe(200);
    expect(result.data?.transcript).toBe("为什么 range 不包含右端点？");
    expect(result.data?.confidence).toBeCloseTo(0.93);
    expect(result.data?.language).toBe("zh");
    expect(result.data?.duration_ms).toBe(4200);

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.url).toBe("https://api.example.test/api/v1/asr");
    expect(request.method).toBe("POST");
    expect(request.headers.get("Authorization")).toBe("Bearer student-access");
    expect(request.headers.get("Idempotency-Key")).toMatch(/^asr-voice-/);
    // The platform must own the multipart Content-Type so the boundary is set;
    // the wrapper deliberately does NOT pin it (and drops the JSON default).
    // (We avoid `request.text()` here — consuming the streamed FormData body in
    // jsdom is slow and the multipart Content-Type already proves the wire
    // shape; the body bytes are exercised by the wrapper-level unit guards and
    // the integration suite.)
    expect(request.headers.get("Content-Type")).toMatch(
      /^multipart\/form-data; boundary=/,
    );
    expect(request.body).toBeInstanceOf(ReadableStream);
  });

  it("rejects unsupported MIME before any network call", async () => {
    const file = new File([new Uint8Array(8)], "q.aac", { type: "audio/aac" });
    const result = await submitAsr({
      body: { file },
      headers: commandHeaders("student-access", "asr-voice"),
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.data).toBeNull();
    expect(result.error).toBeInstanceOf(Error);
    expect(errorMessage(result.error)).toContain("不支持的音频格式");
  });

  it("rejects files over the 10 MiB cap before any network call", async () => {
    // Build a tiny real File, then override its reported size so the test stays
    // fast — allocating a true 10 MiB buffer in jsdom is needlessly slow and
    // the guard only inspects `file.size`, not the bytes.
    const oversized = new File([new Uint8Array(8)], "huge.webm", {
      type: "audio/webm",
    });
    Object.defineProperty(oversized, "size", {
      configurable: true,
      value: MAX_ASR_FILE_BYTES + 1,
    });
    const result = await submitAsr({
      body: { file: oversized },
      headers: commandHeaders("student-access", "asr-voice"),
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.data).toBeNull();
    expect(errorMessage(result.error)).toContain("10 MiB");
  });

  it("accepts all four BE-025 MIME allowlist entries", () => {
    expect([...ASR_ACCEPTED_MIME]).toEqual([
      "audio/wav",
      "audio/webm",
      "audio/ogg",
      "audio/mpeg",
    ]);
  });

  it("exposes the 60s duration cap as a constant", () => {
    expect(MAX_ASR_DURATION_MS).toBe(60_000);
  });

  it("surfaces a 503 as an error result (UI degrades) without throwing", async () => {
    fetchMock.mockResolvedValueOnce(
      asrJson({ detail: "ASR service unavailable" }, 503),
    );
    const result = await submitAsr({
      body: { file: audioFile() },
      headers: commandHeaders("student-access", "asr-voice"),
    });
    expect(result.response.status).toBe(503);
    expect(result.data).toBeNull();
    expect(result.error).toEqual({ detail: "ASR service unavailable" });
  });

  it("tolerates missing optional confidence/language/duration fields in the response", async () => {
    fetchMock.mockResolvedValueOnce(
      asrJson({
        transcript: "列表偶数求和怎么写？",
      }),
    );
    const result = await submitAsr({
      body: { file: audioFile() },
      headers: commandHeaders("student-access", "asr-voice"),
    });
    expect(result.data?.transcript).toBe("列表偶数求和怎么写？");
    expect(result.data?.confidence).toBeUndefined();
    expect(result.data?.language).toBeUndefined();
    expect(result.data?.duration_ms).toBeUndefined();
  });
});
