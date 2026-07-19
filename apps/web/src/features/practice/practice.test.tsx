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

const NODE_ID = "00000000-0000-0000-0000-0000000000aa";

const questionsPayload = [
  {
    question_id: "00000000-0000-0000-0000-0000000000b1",
    node_id: NODE_ID,
    kind: "MULTIPLE_CHOICE",
    prompt: "以下哪个是合法的 Python 变量名？",
    options: ["1st_name", "_name", "class", "my name"],
  },
  {
    question_id: "00000000-0000-0000-0000-0000000000b2",
    node_id: NODE_ID,
    kind: "MULTIPLE_CHOICE",
    prompt: "len('abc') 的返回值是？",
    options: ["2", "3", "4", "None"],
  },
];

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

function questionsThen(
  body: unknown,
  status = 200,
): ReturnType<typeof vi.fn> {
  return vi.fn().mockResolvedValue(json(body, status));
}

describe("practice self-test", () => {
  it("renders questions, submits answers, and shows score with per-question review", async () => {
    fetchMock
      .mockImplementationOnce(questionsThen(questionsPayload))
      .mockImplementationOnce(
        questionsThen({
          score: 0.5,
          correct_count: 1,
          total_count: 2,
          per_question: [
            {
              question_id: questionsPayload[0]!.question_id,
              correct: false,
              explanation: "变量名不能以数字开头。",
            },
            {
              question_id: questionsPayload[1]!.question_id,
              correct: true,
              explanation: null,
            },
          ],
          evidence_id: "EVD-PRACTICE-1",
        }),
      );
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={[`/practice/${NODE_ID}`]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );

    // Both prompts render (all-at-once layout).
    expect(
      await screen.findByRole("heading", { name: "节点自测" }),
    ).toBeVisible();
    expect(
      screen.getByText("以下哪个是合法的 Python 变量名？"),
    ).toBeVisible();
    expect(screen.getByText("len('abc') 的返回值是？")).toBeVisible();

    // Submit is disabled until every question has a selection.
    expect(screen.getByRole("button", { name: "提交自测" })).toBeDisabled();

    // Select one option per question (radio groups).
    const q1 = screen.getByRole("radiogroup", {
      name: "以下哪个是合法的 Python 变量名？",
    });
    const q2 = screen.getByRole("radiogroup", {
      name: "len('abc') 的返回值是？",
    });
    await user.click(within(q1).getByRole("radio", { name: "1st_name" }));
    await user.click(within(q2).getByRole("radio", { name: "3" }));

    await user.click(screen.getByRole("button", { name: "提交自测" }));

    // Score is shown, with correct/incorrect breakdown.
    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: "自测结果" }),
      ).toBeVisible(),
    );
    expect(screen.getByText("1 / 2 题正确")).toBeVisible();

    // Per-question review: incorrect one shows explanation, correct one shows
    // "—" (the explanation for q2 is null on the wire).
    expect(
      screen.getByText("变量名不能以数字开头。"),
    ).toBeVisible();
    const reviewItems = screen.getAllByRole("listitem");
    const q2Review = reviewItems.find((item) =>
      item.textContent?.includes("len('abc') 的返回值是？"),
    );
    expect(q2Review).toBeDefined();
    expect(within(q2Review!).getByText("—")).toBeInTheDocument();

    // The honest mastery note is rendered.
    expect(
      screen.getByText(/已记录为学习证据/),
    ).toBeVisible();

    // The request used Bearer auth + idempotency key.
    const attemptRequest = fetchMock.mock.calls[1]?.[0] as Request;
    expect(attemptRequest.url).toBe(
      "https://api.example.test/api/v1/practice/attempt",
    );
    expect(attemptRequest.method).toBe("POST");
    expect(attemptRequest.headers.get("Authorization")).toBe(
      "Bearer student-access",
    );
    expect(attemptRequest.headers.get("Idempotency-Key")).toMatch(
      /^practice-attempt-/,
    );
    await expect(attemptRequest.clone().json()).resolves.toEqual({
      node_id: NODE_ID,
      answers: [
        {
          question_id: questionsPayload[0]!.question_id,
          selected_answer: "1st_name",
        },
        {
          question_id: questionsPayload[1]!.question_id,
          selected_answer: "3",
        },
      ],
    });
  });

  it("retries with a fresh idempotency key and clears the previous result", async () => {
    fetchMock
      .mockImplementationOnce(questionsThen(questionsPayload))
      .mockImplementationOnce(
        questionsThen({
          score: 0.5,
          correct_count: 1,
          total_count: 2,
          per_question: [],
          evidence_id: "EVD-PRACTICE-1",
        }),
      )
      .mockImplementationOnce(
        // Retry: full score this time.
        questionsThen({
          score: 1,
          correct_count: 2,
          total_count: 2,
          per_question: [],
          evidence_id: "EVD-PRACTICE-2",
        }),
      );
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={[`/practice/${NODE_ID}`]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );

    const q1 = await screen.findByRole("radiogroup", {
      name: "以下哪个是合法的 Python 变量名？",
    });
    const q2 = screen.getByRole("radiogroup", {
      name: "len('abc') 的返回值是？",
    });
    await user.click(within(q1).getByRole("radio", { name: "1st_name" }));
    await user.click(within(q2).getByRole("radio", { name: "3" }));
    await user.click(screen.getByRole("button", { name: "提交自测" }));

    await screen.findByRole("status", { name: "自测结果" });

    await user.click(screen.getByRole("button", { name: "再练一次" }));

    // Result is cleared and the form is reset to the unanswered state.
    await waitFor(() =>
      expect(
        screen.queryByRole("status", { name: "自测结果" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "提交自测" })).toBeDisabled();

    // Re-answer and resubmit to exercise the retry path end-to-end. Questions
    // are cached, so only the attempt call repeats — with a fresh key.
    const q1Retry = screen.getByRole("radiogroup", {
      name: "以下哪个是合法的 Python 变量名？",
    });
    const q2Retry = screen.getByRole("radiogroup", {
      name: "len('abc') 的返回值是？",
    });
    await user.click(within(q1Retry).getByRole("radio", { name: "_name" }));
    await user.click(within(q2Retry).getByRole("radio", { name: "3" }));
    await user.click(screen.getByRole("button", { name: "提交自测" }));

    await screen.findByText("2 / 2 题正确");

    // The retry used a DIFFERENT idempotency key than the first attempt.
    const firstKey = (fetchMock.mock.calls[1]?.[0] as Request).headers.get(
      "Idempotency-Key",
    );
    const retryKey = (fetchMock.mock.calls[2]?.[0] as Request).headers.get(
      "Idempotency-Key",
    );
    expect(retryKey).toMatch(/^practice-attempt-/);
    expect(retryKey).not.toBe(firstKey);
  });

  it("honestly redirects CODE_WRITING-only nodes to the code lab without a form", async () => {
    // 422 signals a CODE_WRITING-only node per BE-023.
    fetchMock.mockImplementationOnce(
      questionsThen(
        { detail: "本节点暂不支持选择型自测" },
        422,
      ),
    );
    render(
      <MemoryRouter initialEntries={[`/practice/${NODE_ID}`]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("heading", {
        name: "本节点通过代码实验练习",
      }),
    ).toBeVisible();
    expect(
      screen.getByText(/本节点练习通过代码实验完成/),
    ).toBeVisible();
    // No form/radio is rendered for CODE_WRITING nodes.
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "提交自测" })).not.toBeInTheDocument();
    // A deep-link to the lab exists.
    expect(
      screen.getByRole("link", { name: "前往代码实验" }),
    ).toHaveAttribute("href", "/lab");
  });

  it("surfaces a load error with a retry affordance", async () => {
    fetchMock.mockImplementationOnce(
      questionsThen({ detail: "服务暂时不可用" }, 500),
    );
    render(
      <MemoryRouter initialEntries={[`/practice/${NODE_ID}`]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("alert", { name: "无法加载节点自测" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "重试" })).toBeVisible();
  });

  it("shows an empty state when the node has no multiple-choice questions", async () => {
    fetchMock.mockImplementationOnce(questionsThen([]));
    render(
      <MemoryRouter initialEntries={[`/practice/${NODE_ID}`]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("status", { name: "暂无可自测题目" }),
    ).toBeVisible();
  });

  it("renders the questions request with student auth", async () => {
    fetchMock.mockImplementationOnce(questionsThen(questionsPayload));
    render(
      <MemoryRouter initialEntries={[`/practice/${NODE_ID}`]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );
    await screen.findByRole("radiogroup", {
      name: "以下哪个是合法的 Python 变量名？",
    });
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.url).toBe(
      `https://api.example.test/api/v1/practice/nodes/${NODE_ID}/questions`,
    );
    expect(request.headers.get("Authorization")).toBe("Bearer student-access");
  });
});
