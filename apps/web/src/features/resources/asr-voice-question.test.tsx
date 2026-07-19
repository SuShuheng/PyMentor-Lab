/**
 * FE-022 — Red tests for the voice-question UI in the tutor page.
 *
 * jsdom does not implement MediaRecorder or navigator.mediaDevices, so we
 * install a minimal, controllable mock before rendering. The tests drive the
 * full happy path (record → transcript → editable preview → submit as a text
 * question) plus the degraded branches the design requires: permission denied,
 * explicit cancel, and a 503 from BE-025.
 *
 * These mirror the FE-019 TTS player tests: stub global `fetch`, render the
 * tutor with a live (non-fixture) session, and assert the user-visible
 * contract rather than the MediaRecorder internals.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
let recorderInstances: FakeMediaRecorder[];
let getUserMediaMock: ReturnType<typeof vi.fn>;

/**
 * Minimal MediaRecorder double. The real API fires `ondataavailable` (with the
 * captured blob) and then `onstop` exactly once when `stop()` is called —
 * whether the stop comes from the student's button or the 60s auto-stop timer.
 * We mirror that: `stop()` delivers a synthetic chunk and fires both handlers,
 * so the same code path is exercised by the explicit-stop and cap-stop tests.
 */
class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = [];
  state: "inactive" | "recording" = "inactive";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  constructor(public readonly stream: MediaStream) {
    FakeMediaRecorder.instances.push(this);
  }

  start(): void {
    this.state = "recording";
  }

  stop(): void {
    if (this.state === "inactive") return;
    this.state = "inactive";
    this.ondataavailable?.({
      data: new Blob([new Uint8Array(16)], { type: "audio/webm" }),
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
  recorderInstances = [];
  FakeMediaRecorder.instances = recorderInstances;
  // navigator.mediaDevices is undefined in jsdom — install a stub.
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: getUserMediaMock,
    },
  });
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderTutor(view?: string) {
  const route = view ? `/tutor?view=${view}` : "/tutor";
  return render(
    <MemoryRouter initialEntries={[route]}>
      <StudentRoutes initialSession={liveStudentSession} />
    </MemoryRouter>,
  );
}

/** A MediaStream double with the surface the recorder relies on. */
function fakeStream(): MediaStream {
  return {
    getTracks: () => [{ stop: vi.fn() }],
  } as unknown as MediaStream;
}

/**
 * Grant mic permission and prime the BE-025 transcript response. The recorder
 * always hits the real `submitAsr` path (it is not fixture-gated), so only the
 * ASR POST needs a response mock. The tutor's 发送问题 button runs the fixture
 * stream under `MODE === "test"` (no chat fetch), so we assert on the composer
 * state rather than the chat wire.
 */
function primeHappyPath(transcript: string) {
  getUserMediaMock.mockResolvedValueOnce(fakeStream());
  fetchMock
    // POST /api/v1/asr
    .mockResolvedValueOnce(
      json({
        transcript,
        confidence: 0.9,
        language: "zh",
        duration_ms: 2000,
      }),
    );
}

describe("FE-022 voice question", () => {
  it("records, transcribes, lets the student edit, then submits the transcript as a text question", async () => {
    const user = userEvent.setup();
    primeHappyPath("为什么 range 不包含右端点？");
    renderTutor();

    await user.click(screen.getByRole("button", { name: "语音提问" }));
    // Permission was requested for the mic only.
    expect(getUserMediaMock).toHaveBeenCalledWith(
      expect.objectContaining({ audio: true }),
    );

    // While recording, the status region is announced.
    await waitFor(() =>
      expect(screen.getByRole("status", { name: "语音录音" })).toBeVisible(),
    );

    // Stop the recording; the recorder double fires onstop (delivering a chunk)
    // exactly like the real API does on stop — whether from the button or cap.
    await user.click(screen.getByRole("button", { name: "停止录音并识别" }));
    expect(recorderInstances[0]).toBeDefined();

    // The transcript lands in the editable textarea (the existing composer).
    const textarea = await screen.findByLabelText("你的问题");
    await waitFor(() => expect(textarea).toHaveValue("为什么 range 不包含右端点？"));
    // A clear "transcribed, you may edit" note is shown.
    expect(
      screen.getByRole("status", { name: "语音转写结果" }),
    ).toHaveTextContent(/可编辑后发送/);

    // The student can edit before submitting.
    await user.clear(textarea);
    await user.type(textarea, "请解释 range 的右端点");
    // The composer now holds the *edited* transcript, ready to submit as a
    // normal text question — this is the "feeds the Q&A flow as a typed
    // question" contract.
    expect(textarea).toHaveValue("请解释 range 的右端点");

    await user.click(screen.getByRole("button", { name: "发送问题" }));
    // The tutor streams an answer from the submitted question — proving the
    // voice-derived text entered the existing Q&A flow end to end.
    await waitFor(() =>
      expect(
        screen.getByRole("article", { name: "辅导回答" }),
      ).toBeVisible(),
    );
  });

  it("does not persist raw audio client-side after the transcript is returned", async () => {
    const user = userEvent.setup();
    primeHappyPath("列表偶数求和怎么写？");
    renderTutor();

    await user.click(screen.getByRole("button", { name: "语音提问" }));
    await user.click(screen.getByRole("button", { name: "停止录音并识别" }));

    // The transcript is present…
    await waitFor(() =>
      expect(screen.getByLabelText("你的问题")).toHaveValue(
        "列表偶数求和怎么写？",
      ),
    );
    // …but the recorder instance is released (track-stopped + dereferenced).
    expect(recorderInstances[0]?.state).toBe("inactive");
    // No <audio> element is rendered for the captured clip.
    expect(document.querySelector("audio")).toBeNull();
  });

  it("shows a helpful message and keeps the keyboard path when mic permission is denied", async () => {
    const user = userEvent.setup();
    getUserMediaMock.mockRejectedValueOnce(
      new DOMException("Permission denied", "NotAllowedError"),
    );
    renderTutor();

    await user.click(screen.getByRole("button", { name: "语音提问" }));

    expect(
      await screen.findByRole("alert", { name: "语音录音失败" }),
    ).toHaveTextContent(/麦克风权限|键盘/);
    // The composer stays usable.
    expect(screen.getByLabelText("你的问题")).toBeEnabled();
    expect(screen.getByRole("button", { name: "发送问题" })).toBeEnabled();
  });

  it("lets the student cancel a recording without uploading anything", async () => {
    const user = userEvent.setup();
    getUserMediaMock.mockResolvedValueOnce(fakeStream());
    renderTutor();

    await user.click(screen.getByRole("button", { name: "语音提问" }));
    await waitFor(() =>
      expect(screen.getByRole("status", { name: "语音录音" })).toBeVisible(),
    );

    await user.click(screen.getByRole("button", { name: "取消录音" }));

    // Recording UI is torn down…
    await waitFor(() =>
      expect(
        screen.queryByRole("status", { name: "语音录音" }),
      ).not.toBeInTheDocument(),
    );
    // …and no ASR upload was attempted.
    const asrCalls = fetchMock.mock.calls.filter((call) => {
      const request = call[0] as Request;
      return request?.url?.includes("/api/v1/asr");
    });
    expect(asrCalls).toHaveLength(0);
    // The original question is untouched.
    expect(screen.getByLabelText("你的问题")).toHaveValue(
      "为什么 range(1, 5) 不包含 5？",
    );
  });

  it("degrades to a typed prompt when ASR returns 503 and never blocks the keyboard flow", async () => {
    const user = userEvent.setup();
    getUserMediaMock.mockResolvedValueOnce(fakeStream());
    fetchMock
      // POST /api/v1/asr → 503
      .mockResolvedValueOnce(json({ detail: "ASR service unavailable" }, 503));
    renderTutor();

    await user.click(screen.getByRole("button", { name: "语音提问" }));
    await user.click(screen.getByRole("button", { name: "停止录音并识别" }));

    expect(
      await screen.findByRole("alert", { name: "语音识别不可用" }),
    ).toHaveTextContent(/语音识别暂不可用，请键入问题/);
    expect(screen.getByLabelText("你的问题")).toBeEnabled();
    expect(screen.getByRole("button", { name: "发送问题" })).toBeEnabled();
  });

  it("auto-stops at the 60s cap without losing the captured audio", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      primeHappyPath("超过六十秒的提问内容");
      renderTutor();
      // userEvent + fake timers: drive clicks via fireEvent.
      fireEvent.click(screen.getByRole("button", { name: "语音提问" }));
      await waitFor(() =>
        expect(screen.getByRole("status", { name: "语音录音" })).toBeVisible(),
      );
      // Advance past the 60s cap; the recorder should auto-stop + upload.
      vi.advanceTimersByTime(60_000);
      await waitFor(() =>
        expect(screen.getByLabelText("你的问题")).toHaveValue(
          "超过六十秒的提问内容",
        ),
      );
    } finally {
      vi.useRealTimers();
    }
  });
});
