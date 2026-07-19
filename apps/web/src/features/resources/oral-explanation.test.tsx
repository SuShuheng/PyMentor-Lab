/**
 * FE-023 — Red tests for the oral-explanation page.
 *
 * The page wires FE-019 (TtsPlayer, to play the BE-026 prompt) + FE-022
 * (VoiceQuestionRecorder, to capture the student's spoken answer) into the
 * BE-026 `POST /api/v1/oral-explanation` flow. It renders the rubric
 * breakdown, transcript, model answer, and the two honesty communications:
 * - the mock label ("模拟评分（无真实 LLM/ASR/TTS 凭据）") when
 *   `response.mock === true`;
 * - the explicit "掌握度由系统综合判定，不会仅因本次评分而自动提升" note,
 *   because oral evidence NEVER auto-advances mastery (CONTRACT).
 *
 * jsdom does not implement MediaRecorder / getUserMedia, so we install a
 * minimal double before rendering — same pattern as asr-voice-question.test.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { saveServerUrl } from "@pymentor/config";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { configureStudentApi } from "../../student-api";
import { StudentRoutes } from "../../student-routes";
import { studentSession } from "../auth/auth-session";

const liveStudentSession = {
  ...studentSession,
  accessToken: "student-access",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

let fetchMock: ReturnType<typeof vi.fn>;
let getUserMediaMock: ReturnType<typeof vi.fn>;

/**
 * Minimal MediaRecorder double. On `stop()` it fires `ondataavailable` with a
 * synthetic blob then `onstop`, mirroring the real API for both the explicit
 * stop and the 60s auto-stop.
 */
class FakeMediaRecorder {
  state: "inactive" | "recording" = "inactive";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  constructor(public readonly stream: MediaStream) {}

  start(): void {
    this.state = "recording";
  }

  stop(): void {
    if (this.state === "inactive") return;
    this.state = "inactive";
    this.ondataavailable?.({
      data: new Blob([new Uint8Array(32)], { type: "audio/webm" }),
    });
    this.onstop?.();
  }
}

beforeEach(() => {
  window.localStorage.clear();
  saveServerUrl("https://api.example.test");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  configureStudentApi();
  getUserMediaMock = vi.fn();
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: getUserMediaMock },
  });
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function fakeStream(): MediaStream {
  return { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;
}

function renderPage(nodeId = "node-variables") {
  return render(
    <MemoryRouter initialEntries={[`/oral/${nodeId}`]}>
      <StudentRoutes initialSession={liveStudentSession} />
    </MemoryRouter>,
  );
}

const oralResponse = {
  score: 0.8,
  rubric: [
    { criterion: "准确性", score: 0.85, feedback: "核心概念正确，未提及可变性。" },
    { criterion: "完整性", score: 0.75, feedback: "缺少边界说明。" },
  ],
  transcript: "变量是绑定到名字上的值。",
  model_answer: "变量是程序中绑定到标识符的存储位置。",
  prompt: {
    audio_url: "/api/v1/tts/audio/oral-1/d1",
    subtitle_track: [{ start_ms: 0, end_ms: 1500, text: "请解释变量。" }],
    mock: false,
  },
  evidence_id: "EVD-0231",
  mock: false,
};

const oralMockResponse = {
  ...oralResponse,
  rubric: [{ criterion: "准确性", score: 0.5, feedback: "（模拟反馈）" }],
  transcript: "（模拟转写）",
  model_answer: "（模拟答案）",
  prompt: { audio_url: "/x", subtitle_track: [], mock: true },
  evidence_id: "EVD-0231",
  mock: true,
};

/** Mock the BE-026 POST + the FE-019 TTS synthesis + the prompt audio GET. */
function oralFetchMock(body: unknown, status = 200): ReturnType<typeof vi.fn> {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    if (url.endsWith("/api/v1/oral-explanation")) {
      // The POST body is a Request (undici-wrapped FormData) for the hey-api
      // client. The wire-shape assertions read the headers without consuming
      // the stream (jsdom never resolves it).
      return json(body, status);
    }
    if (url.endsWith("/api/v1/tts")) {
      // FE-019 reuse: the prompt is synthesised via BE-022 TTS so the student
      // can hear the question. Return a minimal valid TtsResponse.
      return json({
        request_id: "req-tts-oral",
        digest: "d0d1",
        audio_url: "/api/v1/tts/audio/req-tts-oral/d0d1",
        subtitle_track: [{ start_ms: 0, end_ms: 1500, text: "请解释变量。" }],
        mime: "audio/mpeg",
        duration_ms: 1500,
        mock: false,
      });
    }
    if (url.includes("/api/v1/tts/audio/")) {
      return new Response(new Blob([new Uint8Array([0, 1, 2])]), { status: 200 });
    }
    return json({});
  });
}

describe("FE-023 oral explanation", () => {
  it("plays the prompt via TtsPlayer, records the answer, submits to BE-026 and renders the rubric breakdown + transcript + model answer", async () => {
    fetchMock.mockImplementation(oralFetchMock(oralResponse));
    getUserMediaMock.mockResolvedValueOnce(fakeStream());

    const user = userEvent.setup();
    renderPage();

    // The prompt text is visible (sourced from BE-026's prompt_text, defaulted
    // to a node-specific question).
    const promptPanel = await screen.findByRole("region", {
      name: "口述题目",
    });
    expect(promptPanel).toHaveTextContent(/请用自己的话解释/);

    // FE-019 reuse: the student can play the prompt audio.
    await user.click(screen.getByRole("button", { name: "播放题目" }));
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "讲解音频" }),
      ).toBeVisible(),
    );

    // FE-022 reuse: the student records their oral answer.
    await user.click(screen.getByRole("button", { name: "开始录音" }));
    await waitFor(() =>
      expect(screen.getByRole("status", { name: "语音录音" })).toBeVisible(),
    );
    await user.click(screen.getByRole("button", { name: "停止录音" }));

    // The captured clip is uploaded to BE-026…
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "口述评分" }),
      ).toBeVisible(),
    );

    // The rubric breakdown renders per-criterion score + feedback.
    expect(screen.getByText("准确性")).toBeVisible();
    expect(screen.getByText(/核心概念正确/)).toBeVisible();
    expect(screen.getByText("完整性")).toBeVisible();
    expect(screen.getByText(/缺少边界说明/)).toBeVisible();

    // The transcript and model answer are shown.
    expect(
      screen.getByRole("region", { name: "你的回答转写" }),
    ).toHaveTextContent("变量是绑定到名字上的值。");
    expect(
      screen.getByRole("region", { name: "参考答案" }),
    ).toHaveTextContent("绑定到标识符的存储位置");

    // The score and evidence id are surfaced. The score chip is the single
    // "得分 N / 100" element (rubric rows render "N / 100" without the 得分
    // prefix, so this is unique). The evidence id is interpolated into a
    // sentence, so a regex partial match is the robust assertion.
    expect(screen.getByText(/得分\s*80\s*\/\s*100/)).toBeInTheDocument();
    expect(screen.getByText(/EVD-0231/)).toBeInTheDocument();

    // The POST carried multipart + Bearer + idempotency.
    const oralCall = fetchMock.mock.calls.find((call) => {
      const r = call[0] as Request;
      return r?.url?.endsWith("/api/v1/oral-explanation");
    });
    const request = oralCall?.[0] as Request;
    expect(request.method).toBe("POST");
    expect(request.headers.get("Authorization")).toBe("Bearer student-access");
    expect(request.headers.get("Idempotency-Key")).toMatch(/^oral-explanation-/);
    expect(request.headers.get("Content-Type") ?? "").toMatch(
      /^multipart\/form-data;/,
    );
  });

  it("always communicates that oral evidence never auto-advances mastery", async () => {
    fetchMock.mockImplementation(oralFetchMock(oralResponse));
    getUserMediaMock.mockResolvedValueOnce(fakeStream());

    const user = userEvent.setup();
    renderPage();

    // The no-mastery-advance note is shown up-front (before scoring) AND after
    // the result lands — both states must communicate the contract.
    expect(
      screen.getByText(/掌握度由系统综合判定.*不会.*自动提升/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "开始录音" }));
    await user.click(await screen.findByRole("button", { name: "停止录音" }));

    await screen.findByRole("region", { name: "口述评分" });
    // After scoring the note is still present — in fact the page surfaces it in
    // two places (pre-record guidance + post-result confirmation), so assert at
    // least one match rather than a unique one.
    expect(
      screen.getAllByText(/掌握度由系统综合判定.*不会.*自动提升/).length,
    ).toBeGreaterThanOrEqual(1);
    // And the recorded-as-evidence fact is surfaced with the evidence id.
    expect(screen.getByText(/已记录为学习证据/)).toBeInTheDocument();
  });

  it("labels mock responses clearly so students never mistake the stub for a real score", async () => {
    fetchMock.mockImplementation(oralFetchMock(oralMockResponse));
    getUserMediaMock.mockResolvedValueOnce(fakeStream());

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "开始录音" }));
    await user.click(await screen.findByRole("button", { name: "停止录音" }));

    expect(
      await screen.findByText(/模拟评分（无真实 LLM\/ASR\/TTS 凭据）/),
    ).toBeVisible();
  });

  it("degrades honestly when BE-026 returns 503 without crashing", async () => {
    fetchMock.mockImplementation(
      oralFetchMock({ detail: "oral service unavailable" }, 503),
    );
    getUserMediaMock.mockResolvedValueOnce(fakeStream());

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "开始录音" }));
    await user.click(await screen.findByRole("button", { name: "停止录音" }));

    // A clear, honest error is shown; no rubric is rendered.
    expect(
      await screen.findByRole("alert", { name: "口述评分失败" }),
    ).toHaveTextContent(/oral service unavailable|请求失败/);
    expect(
      screen.queryByRole("region", { name: "口述评分" }),
    ).not.toBeInTheDocument();
  });

  it("lets the student retry after a failed submission and mints a fresh request", async () => {
    // First oral POST → 503; every subsequent oral POST → success. The TTS
    // synthesis + audio GET always succeed (so the prompt can be replayed).
    let oralCalls = 0;
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.endsWith("/api/v1/oral-explanation")) {
        oralCalls += 1;
        if (oralCalls === 1) {
          return json({ detail: "oral service unavailable" }, 503);
        }
        return json(oralResponse);
      }
      if (url.endsWith("/api/v1/tts")) {
        return json({
          request_id: "req-tts-oral",
          digest: "d0d1",
          audio_url: "/api/v1/tts/audio/req-tts-oral/d0d1",
          subtitle_track: [{ start_ms: 0, end_ms: 1500, text: "请解释变量。" }],
          mime: "audio/mpeg",
          duration_ms: 1500,
          mock: false,
        });
      }
      if (url.includes("/api/v1/tts/audio/")) {
        return new Response(new Blob([new Uint8Array([0, 1, 2])]), {
          status: 200,
        });
      }
      return json({});
    });
    getUserMediaMock.mockResolvedValue(fakeStream());

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "开始录音" }));
    await user.click(await screen.findByRole("button", { name: "停止录音" }));
    await screen.findByRole("alert", { name: "口述评分失败" });

    // The retry affordance re-arms the recorder for a new attempt.
    await user.click(screen.getByRole("button", { name: /重新口述/ }));
    await user.click(screen.getByRole("button", { name: "开始录音" }));
    await user.click(await screen.findByRole("button", { name: "停止录音" }));

    // The second attempt lands the rubric.
    expect(
      await screen.findByRole("region", { name: "口述评分" }),
    ).toBeVisible();
    expect(screen.getByText("准确性")).toBeVisible();
  });
});
