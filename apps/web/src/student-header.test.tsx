/**
 * Stage C — Student header button wiring (FE-C).
 *
 * The header has three buttons that previously had no onClick:
 *  - 今日计划 (task-progress)  → navigate to /today
 *  - 通知 (Bell)              → toggle a notifications panel fed by
 *                                /api/v1/reviews/due + /api/v1/learning/today
 *  - 打开个人菜单 (UserCircle) → toggle a profile dropdown with profile/growth
 *                                links and a sign-out action
 *
 * These tests follow the same fetch-stub pattern as practice.test.tsx and
 * oral-explanation.test.tsx (saveServerUrl + vi.stubGlobal("fetch")). The
 * auth-session is seeded directly via `initialSession` so no login round-trip
 * is needed.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { saveServerUrl } from "@pymentor/config";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StudentRoutes } from "./student-routes";
import { studentSession } from "./features/auth/auth-session";

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

beforeEach(() => {
  window.localStorage.clear();
  saveServerUrl("https://api.example.test");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

function renderStudent(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <StudentRoutes initialSession={liveStudentSession} />
    </MemoryRouter>,
  );
}

describe("student header button wiring (Stage C)", () => {
  it("navigates to the today page when 今日计划 is clicked", async () => {
    const user = userEvent.setup();
    // Start on a different page so the navigation is observable.
    renderStudent("/growth");

    await user.click(screen.getByRole("button", { name: /今日计划/ }));

    expect(
      await screen.findByRole("heading", { name: "今日学习工作台" }),
    ).toBeVisible();
  });

  it("opens the notifications panel and shows a due review from /reviews/due", async () => {
    // The panel fires two concurrent requests (reviews/due + learning/today).
    // Return a fresh Response per call so each consumer can read its own body.
    const reviewPayload = [
      {
        course_id: "course-py",
        due_at: "2026-07-19T23:59:00Z",
        id: "review-loop-boundary",
        node_id: "00000000-0000-0000-0000-0000000000a1",
        reschedule_count: 0,
        scenario_key: "loop-off-by-one",
        status: "DUE",
        version: 1,
      },
    ];
    fetchMock.mockImplementation(() => Promise.resolve(json(reviewPayload)));

    const user = userEvent.setup();
    renderStudent("/today");

    const bell = screen.getByRole("button", { name: "通知" });
    await user.click(bell);

    const panel = await screen.findByRole("menu", { name: "通知中心" });
    // FE Issue 6: the raw node UUID must NOT appear in the notification text.
    // The student sees a human-readable "到期复测" label plus the scenario key.
    expect(panel).not.toHaveTextContent("00000000");
    expect(panel).not.toHaveTextContent("0000000000a1");
    expect(panel).toHaveTextContent("loop-off-by-one");
    expect(
      await within(panel).findByRole("menuitem", { name: /到期复测/ }),
    ).toBeVisible();
  });

  it("shows 暂无新通知 when both data sources are empty", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json([])));

    const user = userEvent.setup();
    renderStudent("/today");

    await user.click(screen.getByRole("button", { name: "通知" }));

    const panel = await screen.findByRole("menu", { name: "通知中心" });
    expect(panel).toHaveTextContent("暂无新通知");
  });

  it("opens the profile dropdown with 我的画像 / 我的成长 / 退出登录", async () => {
    const user = userEvent.setup();
    renderStudent("/today");

    await user.click(screen.getByRole("button", { name: "打开个人菜单" }));

    const menu = await screen.findByRole("menu", { name: "学生个人菜单" });
    expect(
      within(menu).getByRole("menuitem", { name: "我的画像" }),
    ).toBeVisible();
    expect(
      within(menu).getByRole("menuitem", { name: "我的成长" }),
    ).toBeVisible();
    expect(
      within(menu).getByRole("menuitem", { name: "退出登录" }),
    ).toBeVisible();
  });

  it("signs out and returns to the login page", async () => {
    const user = userEvent.setup();
    renderStudent("/today");

    await user.click(screen.getByRole("button", { name: "打开个人菜单" }));

    const logoutItem = await screen.findByRole("menuitem", { name: "退出登录" });
    await user.click(logoutItem);

    expect(
      await screen.findByRole("heading", { name: "欢迎回来" }),
    ).toBeVisible();
  });

  it("dismisses the notifications panel on Escape", async () => {
    fetchMock.mockResolvedValue(json([]));
    const user = userEvent.setup();
    renderStudent("/today");

    await user.click(screen.getByRole("button", { name: "通知" }));
    const panel = await screen.findByRole("menu", { name: "通知中心" });
    expect(panel).toBeVisible();

    await user.keyboard("{Escape}");

    await waitFor(() =>
      expect(
        screen.queryByRole("menu", { name: "通知中心" }),
      ).not.toBeInTheDocument(),
    );
  });
});
