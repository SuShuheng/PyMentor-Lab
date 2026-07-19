import { render, screen, waitFor } from "@testing-library/react";
import { saveServerUrl } from "@pymentor/config";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StudentRoutes } from "../../student-routes";
import { studentSession } from "../auth/auth-session";

const profileSnapshot = {
  dimensions: [
    ["CONCEPT_KNOWLEDGE", "函数 · 循环", 0.76],
    ["EXECUTION_MODEL", "作用域 · 控制流", 0.68],
    ["IMPLEMENTATION", "函数封装 · 列表处理", 0.73],
    ["DECOMPOSITION", "步骤拆分 · 伪代码", 0.61],
    ["DEBUGGING", "异常阅读 · 定位", 0.7],
    ["TESTING", "边界值 · 自测", 0.58],
    ["TRANSFER", "变式迁移 · 综合任务", 0.64],
    ["INDEPENDENCE_SUPPORT", "独立运行 · 提示预算", 0.72],
  ].map(([dimension, scope_key, score]) => ({
    confidence: 0.9,
    dimension,
    scope_key,
    score,
    support_level: 1,
  })),
  id: "00000000-0000-0000-0000-000000000031",
  source_event_id: "EVD-2048",
  student_id: "student-001",
  version: 7,
};

const liveStudentSession = {
  ...studentSession,
  accessToken: "student-access",
};

const onboardingResponse = {
  evidence_event_id: "EVD-ONBOARD-1",
  profile_version_id: "00000000-0000-0000-0000-000000000040",
  profile_version: 1,
  replan_requested: false,
};

let fetchMock = vi.fn();

beforeEach(() => {
  window.localStorage.clear();
  saveServerUrl("https://api.example.test");
  fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(profileSnapshot), {
      headers: { "Content-Type": "application/json" },
      status: 200,
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe("conversational onboarding", () => {
  it("advances an explicit, recoverable diagnosis conversation", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/onboarding"]}>
        <StudentRoutes initialSession={studentSession} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "建立你的学习画像" })).toBeVisible();
    expect(screen.getByRole("progressbar", { name: "画像构建进度" })).toHaveAttribute(
      "aria-valuenow",
      "1",
    );
    expect(screen.getByRole("status", { name: "对话进度" })).toHaveTextContent("第 1 步，共 5 步");

    await user.click(screen.getByRole("button", { name: "有一点基础" }));

    expect(screen.getByRole("status", { name: "对话进度" })).toHaveTextContent("第 2 步，共 5 步");
    expect(window.localStorage.getItem("pymentor.onboardingStep")).toBe("1");
  });

  it("keeps reconnect and incomplete-diagnosis states actionable", () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={["/onboarding?view=reconnecting"]}>
        <StudentRoutes initialSession={studentSession} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("alert", { name: "正在重新连接" })).toHaveTextContent(
      "已保留当前对话进度",
    );
    expect(screen.getByRole("button", { name: "立即重连" })).toBeVisible();

    unmount();
    render(
      <MemoryRouter initialEntries={["/onboarding?view=incomplete"]}>
        <StudentRoutes initialSession={studentSession} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("alert", { name: "诊断尚未完成" })).toHaveTextContent(
      "不会生成正式画像版本",
    );
  });

  it("submits mapped answers to the onboarding endpoint and clears saved progress on success", async () => {
    fetchMock
      .mockReset()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(onboardingResponse), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        }),
      )
      .mockResolvedValue(
        new Response(JSON.stringify(profileSnapshot), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        }),
      );
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/onboarding"]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );

    // Answer all 5 questions in order. The choice labels mirror the question
    // array in onboarding-pages.tsx.
    await user.click(screen.getByRole("button", { name: "做过完整项目" }));
    await user.click(screen.getByRole("button", { name: "准备竞赛或项目" }));
    await user.click(screen.getByRole("button", { name: "阅读错误信息" }));
    await user.click(screen.getByRole("button", { name: "可运行代码" }));
    await user.click(screen.getByRole("button", { name: "4 小时以上" }));

    // Final step exposes the submit control. Trigger the backend submission.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "提交并生成初始画像" })).toBeVisible(),
    );
    await user.click(screen.getByRole("button", { name: "提交并生成初始画像" }));

    await waitFor(() => {
      const request = fetchMock.mock.calls[0]?.[0] as Request;
      expect(request).toBeDefined();
      expect(request.url).toBe("https://api.example.test/api/v1/profiles/onboarding");
      expect(request.method).toBe("POST");
      expect(request.headers.get("Authorization")).toBe("Bearer student-access");
      expect(request.headers.get("Idempotency-Key")).toMatch(/^onboarding-/);
    });
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    await expect(request.clone().json()).resolves.toEqual({
      answers: {
        prior_experience: "做过完整项目",
        primary_goal: "准备竞赛或项目",
        error_strategy: "阅读错误信息",
        preferred_exercise: "可运行代码",
        weekly_band: "4 小时以上",
      },
      expected_profile_version: 0,
    });

    // On success the saved step must be cleared and the user routed onward.
    await waitFor(() => expect(window.localStorage.getItem("pymentor.onboardingStep")).toBeNull());
  });

  it("surfaces a visible error and keeps progress when the onboarding submission fails", async () => {
    fetchMock.mockReset().mockResolvedValue(
      new Response(JSON.stringify({ detail: "画像服务暂时不可用" }), {
        headers: { "Content-Type": "application/json" },
        status: 500,
      }),
    );
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/onboarding"]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("button", { name: "有一点基础" }));
    await user.click(screen.getByRole("button", { name: "跟上课堂进度" }));
    await user.click(screen.getByRole("button", { name: "逐行检查代码" }));
    await user.click(screen.getByRole("button", { name: "短小例题" }));
    await user.click(screen.getByRole("button", { name: "2–4 小时" }));

    await user.click(screen.getByRole("button", { name: "提交并生成初始画像" }));

    await waitFor(() =>
      expect(screen.getByRole("alert", { name: "提交错误" })).toBeVisible(),
    );
    // Progress is preserved so the student can retry without re-answering.
    expect(window.localStorage.getItem("pymentor.onboardingStep")).not.toBeNull();
  });
});

describe("evidence-linked profile", () => {
  it("shows all eight server dimensions, node summaries and profile version", async () => {
    render(
      <MemoryRouter initialEntries={["/growth/profile"]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("figure", { name: "八维能力画像" })).toBeVisible();
    for (const dimension of [
      "概念知识掌握",
      "代码执行模型",
      "编程实现能力",
      "问题分解与算法表达能力",
      "调试与错误定位能力",
      "测试与边界意识",
      "迁移与综合应用能力",
      "独立完成度与支架需求",
    ]) {
      expect(screen.getByRole("rowheader", { name: dimension })).toBeVisible();
    }
    expect(screen.getByRole("heading", { name: "画像版本 v7" })).toBeVisible();
    expect(screen.getByText("按知识节点聚合")).toBeVisible();
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.url).toBe("https://api.example.test/api/v1/profiles/current");
    expect(request.headers.get("Authorization")).toBe("Bearer student-access");
  });

  it("progressively discloses evidence and submits a dispute", async () => {
    fetchMock
      .mockReset()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(profileSnapshot), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "dispute-001",
            profile_version_id: profileSnapshot.id,
            reason: "这次循环练习未计入画像。",
          }),
          { headers: { "Content-Type": "application/json" }, status: 201 },
        ),
      );
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/growth/profile"]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );

    await screen.findByRole("figure", { name: "八维能力画像" });
    expect(screen.queryByRole("region", { name: "画像证据" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看画像证据" }));
    expect(screen.getByRole("region", { name: "画像证据" })).toHaveTextContent("EVD-2048");

    await user.click(screen.getByRole("button", { name: "对画像提出异议" }));
    expect(screen.getByRole("dialog", { name: "提交画像异议" })).toBeVisible();
    await user.type(screen.getByRole("textbox", { name: "异议说明" }), "这次循环练习未计入画像。 ");
    await user.click(screen.getByRole("button", { name: "提交异议" }));

    await waitFor(() =>
      expect(screen.getByRole("status", { name: "异议状态" })).toHaveTextContent("异议已提交"),
    );
    const request = fetchMock.mock.calls[1]?.[0] as Request;
    expect(request.url).toBe("https://api.example.test/api/v1/profiles/disputes");
    expect(request.headers.get("Authorization")).toBe("Bearer student-access");
    expect(request.headers.get("Idempotency-Key")).toMatch(/^profile-dispute-/);
    await expect(request.clone().json()).resolves.toEqual({
      profile_version_id: profileSnapshot.id,
      reason: "这次循环练习未计入画像。",
    });
  });
});
