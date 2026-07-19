/**
 * FE-023 — Red tests for the oral-explanation typed wrapper
 * (BE-026 `POST /api/v1/oral-explanation`).
 *
 * These mirror the FE-021/022 wrapper tests: stub `fetch`, assert the wire
 * shape (multipart with node_id + prompt_text + audio, Bearer + idempotency,
 * MIME/size guardrails) and the typed `{ data, error, response }` result.
 *
 * Honesty contract (BE-026):
 * - The response carries `mock: true` when the backend has no real
 *   LLM/ASR/TTS credentials. The wrapper surfaces that flag unchanged so the
 *   UI MUST label it; the wrapper never claims a real score.
 * - The wrapper performs NO mastery mutation. It only carries the server's
 *   `evidence_id` back; the UI communicates that mastery is decided
 *   server-side and never auto-advanced.
 */
import { saveServerUrl } from "@pymentor/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { commandHeaders, configureStudentApi } from "../../student-api";
import {
  MAX_ORAL_AUDIO_BYTES,
  ORAL_ACCEPTED_MIME,
  scoreOralExplanation,
} from "./oral-api";

function oralJson(body: unknown, status = 200): Response {
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

function audioClip(bytes = 0x100): Blob {
  return new Blob([new Uint8Array(bytes)], { type: "audio/webm" });
}

describe("FE-023 oral-api scoreOralExplanation", () => {
  it("POSTs multipart (node_id + prompt_text + audio) to /api/v1/oral-explanation with Bearer + idempotency and returns the rubric", async () => {
    fetchMock.mockResolvedValueOnce(
      oralJson({
        score: 0.8,
        rubric: [
          {
            criterion: "准确性",
            score: 0.85,
            feedback: "核心概念正确，但未提及可变性。",
          },
          { criterion: "完整性", score: 0.75, feedback: "缺少边界说明。" },
        ],
        transcript: "变量是绑定到名字上的值……",
        model_answer: "变量是程序中绑定到标识符的存储位置……",
        prompt: {
          audio_url: "/api/v1/tts/audio/oral-1/d1",
          subtitle_track: [{ start_ms: 0, end_ms: 1500, text: "请解释变量。" }],
          mock: false,
        },
        evidence_id: "EVD-0231",
        mock: false,
      }),
    );

    const result = await scoreOralExplanation({
      body: {
        node_id: "node-variables",
        prompt_text: "请用自己的话解释变量是什么。",
        audio: audioClip(),
      },
      headers: commandHeaders("student-access", "oral-explanation"),
    });

    expect(result.response.status).toBe(200);
    expect(result.data?.score).toBeCloseTo(0.8);
    expect(result.data?.rubric).toHaveLength(2);
    expect(result.data?.rubric[0]?.criterion).toBe("准确性");
    expect(result.data?.rubric[0]?.feedback).toContain("可变性");
    expect(result.data?.transcript).toContain("变量");
    expect(result.data?.model_answer).toContain("存储位置");
    expect(result.data?.prompt.audio_url).toBe("/api/v1/tts/audio/oral-1/d1");
    expect(result.data?.evidence_id).toBe("EVD-0231");
    expect(result.data?.mock).toBe(false);

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.url).toBe("https://api.example.test/api/v1/oral-explanation");
    expect(request.method).toBe("POST");
    expect(request.headers.get("Authorization")).toBe("Bearer student-access");
    expect(request.headers.get("Idempotency-Key")).toMatch(/^oral-explanation-/);
    // The wrapper must NOT force `application/json` on a multipart body — it
    // drops the runtime default so undici stamps the boundary.
    expect(request.headers.get("Content-Type") ?? "").toMatch(
      /^multipart\/form-data;\s+boundary=/,
    );
    // The body is a stream built from the FormData (three parts: node_id,
    // prompt_text, audio). Reading the stream back is unreliable in jsdom
    // (undici serialises lazily and the body never resolves), so we assert the
    // load-bearing fact the same way the FE-021 OCR wrapper test does: a body
    // WAS attached and it is multipart. Field-level coverage is provided by
    // the UI test, which inspects the captured FormData parts via the fetch
    // spy before they are wrapped into a Request.
    expect(request.body).not.toBeNull();
    expect(request.headers.get("Content-Type")).not.toMatch(/^application\/json/);
  });

  it("rejects unsupported audio MIME before any network call", async () => {
    const clip = new Blob([new Uint8Array(8)], { type: "video/mp4" });
    const result = await scoreOralExplanation({
      body: {
        node_id: "node-variables",
        prompt_text: "请解释变量。",
        audio: clip,
      },
      headers: commandHeaders("student-access", "oral-explanation"),
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.data).toBeNull();
    expect(result.error).toBeInstanceOf(Error);
    expect(String((result.error as Error)?.message)).toContain("不支持的音频格式");
  });

  it("rejects clips over the 25 MiB cap before any network call", async () => {
    const oversized = {
      type: "audio/webm",
      size: MAX_ORAL_AUDIO_BYTES + 1,
    } as unknown as Blob;
    const result = await scoreOralExplanation({
      body: {
        node_id: "node-variables",
        prompt_text: "请解释变量。",
        audio: oversized,
      },
      headers: commandHeaders("student-access", "oral-explanation"),
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.data).toBeNull();
    expect(String((result.error as Error)?.message)).toContain("25 MiB");
  });

  it("exposes the BE-026 audio MIME allowlist (wav/webm/ogg/mp3)", () => {
    expect([...ORAL_ACCEPTED_MIME]).toEqual([
      "audio/wav",
      "audio/webm",
      "audio/ogg",
      "audio/mpeg",
    ]);
  });

  it("surfaces mock:true unchanged so the UI can label it honestly", async () => {
    fetchMock.mockResolvedValueOnce(
      oralJson({
        score: 0.5,
        rubric: [{ criterion: "准确性", score: 0.5, feedback: "（模拟）" }],
        transcript: "（模拟转写）",
        model_answer: "（模拟答案）",
        prompt: { audio_url: "/x", subtitle_track: [], mock: true },
        evidence_id: "EVD-0231",
        mock: true,
      }),
    );
    const result = await scoreOralExplanation({
      body: {
        node_id: "node-variables",
        prompt_text: "请解释变量。",
        audio: audioClip(),
      },
      headers: commandHeaders("student-access", "oral-explanation"),
    });
    expect(result.data?.mock).toBe(true);
  });

  it("surfaces a 503 as an error result (UI degrades) without throwing", async () => {
    fetchMock.mockResolvedValueOnce(
      oralJson({ detail: "oral explanation service unavailable" }, 503),
    );
    const result = await scoreOralExplanation({
      body: {
        node_id: "node-variables",
        prompt_text: "请解释变量。",
        audio: audioClip(),
      },
      headers: commandHeaders("student-access", "oral-explanation"),
    });
    expect(result.response.status).toBe(503);
    expect(result.data).toBeNull();
    expect(result.error).toEqual({ detail: "oral explanation service unavailable" });
  });
});
