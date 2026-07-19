import { render, screen, waitFor, within } from "@testing-library/react";
import { saveServerUrl } from "@pymentor/config";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StudentRoutes } from "../../student-routes";
import { studentSession } from "../auth/auth-session";

const liveStudentSession = {
  ...studentSession,
  accessToken: "student-access",
};

const ttsResponse = {
  request_id: "req-tts-1",
  digest: "d0d1d2d3",
  audio_url: "/api/v1/tts/audio/req-tts-1/d0d1d2d3",
  subtitle_track: [
    { start_ms: 0, end_ms: 1500, text: "循环边界。" },
    { start_ms: 1500, end_ms: 3500, text: "右端点不取到。" },
  ],
  mime: "audio/mpeg",
  duration_ms: 3500,
  mock: false,
};

const ttsMockResponse = {
  ...ttsResponse,
  request_id: "req-tts-mock",
  mock: true,
};

function json(body: unknown, status = 200): Response {
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
});

afterEach(() => vi.unstubAllGlobals());

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return (input as Request).url;
}

function ttsFetchMock(
  ttsBody: unknown,
  ttsStatus = 200,
): ReturnType<typeof vi.fn> {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = urlOf(input);
    if (url.endsWith("/api/v1/tts")) return json(ttsBody, ttsStatus);
    if (url.includes("/api/v1/tts/audio/")) {
      return new Response(new Blob([new Uint8Array([0, 1, 2])]), {
        status: 200,
      });
    }
    return json({});
  });
}

function renderTutorView(view?: string) {
  const route = view ? `/tutor?view=${view}` : "/tutor";
  return render(
    <MemoryRouter initialEntries={[route]}>
      <StudentRoutes initialSession={liveStudentSession} />
    </MemoryRouter>,
  );
}

/**
 * Drive the tutor fixture stream to completion (the "播放讲解" affordance only
 * mounts once `stream.done` is true). In test mode the TutorPage uses fixture
 * events and performs NO fetch for the chat path, so the only fetch the TTS
 * feature issues is the POST /api/v1/tts itself.
 */
async function tutorAnswerDone(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "发送问题" }));
  await waitFor(() =>
    expect(
      screen.getByRole("status", { name: "辅导流状态" }),
    ).toHaveTextContent("回答完成"),
  );
}

describe("FE-019 TTS playback", () => {
  it("posts the answer text to BE-022 and renders audio + subtitles from the response", async () => {
    // The only fetch issued in test mode is the TTS POST (the tutor stream is
    // fixture-driven). The authenticated audio GET is mocked as a tiny blob.
    fetchMock.mockImplementation(ttsFetchMock(ttsResponse));

    const user = userEvent.setup();
    renderTutorView();
    await tutorAnswerDone(user);
    await user.click(screen.getByRole("button", { name: "播放讲解" }));

    // The <audio> element is present and bound to the authenticated audio_url.
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "讲解音频" }),
      ).toBeVisible(),
    );

    const audio = screen.getByTestId("tts-audio") as HTMLAudioElement;
    expect(audio.tagName).toBe("AUDIO");

    // Subtitles render from the response.
    const subtitleList = screen.getByRole("list", { name: "讲解字幕" });
    expect(within(subtitleList).getByText("循环边界。")).toBeInTheDocument();
    expect(
      within(subtitleList).getByText("右端点不取到。"),
    ).toBeInTheDocument();

    // The TTS request used Bearer auth + idempotency key + carried the text.
    const ttsCall = fetchMock.mock.calls.find((call) =>
      urlOf(call[0] as RequestInfo | URL).endsWith("/api/v1/tts"),
    );
    const ttsRequest = ttsCall?.[0] as Request;
    expect(ttsRequest.method).toBe("POST");
    expect(ttsRequest.headers.get("Authorization")).toBe(
      "Bearer student-access",
    );
    expect(ttsRequest.headers.get("Idempotency-Key")).toMatch(/^tts-/);
    await expect(ttsRequest.clone().json()).resolves.toMatchObject({
      text: expect.stringContaining("range"),
    });

    // The audio GET is authenticated too. It is issued via fetch(url, opts)
    // with a string URL, so locate it by URL then read the headers opts.
    const audioCall = fetchMock.mock.calls.find((call) =>
      urlOf(call[0] as RequestInfo | URL).includes("/api/v1/tts/audio/"),
    );
    const audioHeaders = (audioCall?.[1] as RequestInit | undefined)?.headers
      ? new Headers((audioCall?.[1] as RequestInit).headers as HeadersInit)
      : (audioCall?.[0] as Request).headers;
    expect(audioHeaders.get("Authorization")).toBe("Bearer student-access");
  });

  it("labels mock TTS responses clearly so students never mistake them for real audio", async () => {
    fetchMock.mockImplementation(ttsFetchMock(ttsMockResponse));

    const user = userEvent.setup();
    renderTutorView();
    await tutorAnswerDone(user);
    await user.click(screen.getByRole("button", { name: "播放讲解" }));

    expect(
      await screen.findByText(/模拟语音（无真实 TTS 凭据）/),
    ).toBeVisible();
  });

  it("never blocks the answer when TTS is unavailable (503 degrades to text-only)", async () => {
    fetchMock.mockImplementation(ttsFetchMock({ detail: "TTS unavailable" }, 503));

    const user = userEvent.setup();
    renderTutorView();
    await tutorAnswerDone(user);
    await user.click(screen.getByRole("button", { name: "播放讲解" }));

    // The answer remains visible (never blocked).
    expect(
      screen.getByRole("article", { name: "辅导回答" }),
    ).toBeVisible();
    // The audio region is NOT rendered.
    expect(
      screen.queryByRole("region", { name: "讲解音频" }),
    ).not.toBeInTheDocument();
    // A clear, honest fallback note is rendered instead.
    expect(
      await screen.findByText(/讲解音频暂不可用/),
    ).toBeVisible();
  });

  it("highlights the current subtitle based on audio currentTime and seeks on click", async () => {
    fetchMock.mockImplementation(ttsFetchMock(ttsResponse));

    const user = userEvent.setup();
    renderTutorView();
    await tutorAnswerDone(user);
    await user.click(screen.getByRole("button", { name: "播放讲解" }));

    const audio = (await screen.findByTestId(
      "tts-audio",
    )) as HTMLAudioElement;
    // jsdom fires timeupdate only when we dispatch it; simulate playback
    // jumping into the second cue (1500ms..3500ms).
    Object.defineProperty(audio, "currentTime", {
      configurable: true,
      get: () => 2.0,
      set: () => undefined,
    });
    audio.dispatchEvent(new Event("timeupdate"));

    const subtitleList = screen.getByRole("list", { name: "讲解字幕" });
    // The timeupdate handler setState is async; wait for the second cue to be
    // marked active.
    await waitFor(() =>
      expect(
        within(subtitleList)
          .getByText("右端点不取到。")
          .closest("li")
          ?.getAttribute("aria-current"),
      ).toBe("true"),
    );

    // Clicking the first subtitle seeks the audio back to its start_ms.
    const firstItem = within(subtitleList)
      .getByText("循环边界。")
      .closest("li");
    // Restore a settable currentTime so the seek is observable.
    let seekedTo = -1;
    Object.defineProperty(audio, "currentTime", {
      configurable: true,
      get: () => seekedTo,
      set: (value: number) => {
        seekedTo = value;
      },
    });
    const firstButton = within(firstItem!).getByRole("button");
    await user.click(firstButton);
    expect(seekedTo).toBe(0);
  });
});
