import { saveServerUrl } from "@pymentor/config";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StudentRoutes } from "../../student-routes";
import { studentSession } from "../auth/auth-session";

const liveStudentSession = {
  ...studentSession,
  accessToken: "student-access",
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  window.localStorage.clear();
  saveServerUrl("https://api.example.test");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

function renderLab(route = "/lab") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <StudentRoutes initialSession={studentSession} />
    </MemoryRouter>,
  );
}

describe("controlled notebook", () => {
  it("runs code through an explicit lifecycle and reports visible/hidden tests", async () => {
    const user = userEvent.setup();
    renderLab();

    expect(
      (
        screen.getByRole("textbox", {
          name: "Python 代码编辑器",
        }) as HTMLTextAreaElement
      ).value,
    ).toContain("def sum_even");
    await user.click(screen.getByRole("button", { name: "运行代码" }));
    expect(screen.getByRole("status", { name: "运行状态" })).toHaveTextContent(
      "正在安全沙箱中运行",
    );

    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: "运行状态" }),
      ).toHaveTextContent("运行完成"),
    );
    expect(
      screen.getByRole("list", { name: "可见测试结果" }),
    ).toHaveTextContent("3 / 3 通过");
    expect(
      screen.getByText("隐藏测试：2 / 2 通过（测试内容不公开）"),
    ).toBeVisible();
    expect(screen.getByText(/测试通过不等于知识已掌握/)).toBeVisible();
  });

  it("cancels a running job without showing a false success", async () => {
    const user = userEvent.setup();
    renderLab();

    await user.click(screen.getByRole("button", { name: "运行代码" }));
    await user.click(screen.getByRole("button", { name: "取消运行" }));

    expect(screen.getByRole("status", { name: "运行状态" })).toHaveTextContent(
      "运行已取消",
    );
    expect(
      screen.queryByText("隐藏测试：2 / 2 通过（测试内容不公开）"),
    ).not.toBeInTheDocument();
  });

  it("bounds long output and distinguishes user code from platform failures", () => {
    const { unmount } = renderLab("/lab?view=long-output");
    expect(screen.getByRole("log", { name: "程序输出" })).toHaveTextContent(
      "输出已截断",
    );

    unmount();
    renderLab("/lab?view=user-error");
    expect(
      screen.getByRole("alert", { name: "代码运行错误" }),
    ).toHaveTextContent("IndexError");

    unmount();
    renderLab("/lab?view=platform-error");
    expect(
      screen.getByRole("alert", { name: "平台运行失败" }),
    ).toHaveTextContent("不会计入学习证据");
  });

  it("reveals bounded hints and keeps revision history", async () => {
    const user = userEvent.setup();
    renderLab();

    expect(screen.getByText("提示预算 0 / 3")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "使用一级提示" }));
    expect(screen.getByRole("status", { name: "提示内容" })).toHaveTextContent(
      "先检查循环范围",
    );
    expect(screen.getByText("提示预算 1 / 3")).toBeVisible();
    expect(
      screen.getByRole("list", { name: "代码修订历史" }),
    ).toHaveTextContent("v3 · 当前版本");
  });

  it("submits only the latest successfully tested revision", async () => {
    const user = userEvent.setup();
    renderLab();

    const submitButton = screen.getByRole("button", { name: "提交本次练习" });
    expect(submitButton).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "运行代码" }));
    await waitFor(() => expect(submitButton).toBeEnabled());
    await user.click(submitButton);

    expect(screen.getByRole("status", { name: "提交状态" })).toHaveTextContent(
      "正在提交已测试版本",
    );
    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: "提交状态" }),
      ).toHaveTextContent("提交成功 · SUB-LOOP-2407"),
    );
    expect(screen.getByText(/提交不会直接改变掌握状态/)).toBeVisible();
  });
});

describe("FE Issue 1 — dynamic task version after submit", () => {
  const TASK_INSTANCE_ID = "00000000-0000-0000-0000-000000000901";

  // The trace link in NotebookPage must reflect the LIVE taskVersion state,
  // not a hardcoded constant. We gate the link on the presence of a task
  // instance (rather than the global test-fixture flag) so that whenever a
  // real task instance is loaded the link carries its version — and after a
  // successful submit the page adopts the bumped version returned by
  // TaskSubmissionResponse, so subsequent run/trace/submit calls do not hit
  // HTTP 409 with a stale expected_task_version.
  //
  // The full live submit-then-bump cycle cannot be exercised here because the
  // notebook's run/submit handlers short-circuit on USING_TEST_FIXTURES; the
  // version-adoption line (`setTaskVersion(mastery.data.version)`) is verified
  // by code inspection. This test guards the dynamic-link gating that makes
  // the live version reachable at all.
  it("builds the trace link from the URL version when a task instance is present", () => {
    saveServerUrl("https://api.example.test");
    vi.stubGlobal("fetch", vi.fn());

    render(
      <MemoryRouter
        initialEntries={[
          `/lab?task_instance_id=${TASK_INSTANCE_ID}&version=3`,
        ]}
      >
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );

    const traceLink = screen.getByRole("link", { name: /打开执行轨迹/ });
    // The link carries the task instance id and the version from the URL,
    // rather than the bare "/lab/trace" fixture path.
    expect(traceLink).toHaveAttribute(
      "href",
      `/lab/trace?task_instance_id=${TASK_INSTANCE_ID}&version=3`,
    );
  });

  it("falls back to the plain trace page when no task instance is present (fixture/demo)", () => {
    render(
      <MemoryRouter initialEntries={["/lab"]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: /打开执行轨迹/ })).toHaveAttribute(
      "href",
      "/lab/trace",
    );
  });
});

describe("trace playback", () => {
  it("steps through deterministic frames and records a prediction", async () => {
    const user = userEvent.setup();
    renderLab("/lab/trace");

    expect(screen.getByRole("heading", { name: "代码执行轨迹" })).toBeVisible();
    expect(
      screen.getByRole("status", { name: "当前轨迹步骤" }),
    ).toHaveTextContent("步骤 1 / 4");
    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(
      screen.getByRole("status", { name: "当前轨迹步骤" }),
    ).toHaveTextContent("步骤 2 / 4");

    await user.click(screen.getByRole("button", { name: "播放轨迹" }));
    expect(screen.getByRole("button", { name: "暂停播放" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "暂停播放" }));
    expect(screen.getByRole("button", { name: "播放轨迹" })).toBeVisible();

    await user.click(screen.getByRole("radio", { name: "i 将变为 2" }));
    await user.click(screen.getByRole("button", { name: "提交关键帧预测" }));
    expect(
      screen.getByRole("status", { name: "预测证据状态" }),
    ).toHaveTextContent("预测已记录为证据 EVD-TRACE-302");
  });
});

describe("FE-021 error-screenshot OCR upload", () => {
  function ocrJson(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
      headers: { "Content-Type": "application/json" },
      status,
    });
  }

  function pngFile(name = "error.png", bytes = 0x100): File {
    return new File([new Uint8Array(bytes)], name, { type: "image/png" });
  }

  it("does NOT offer 上传截图报错 when the run succeeded", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/lab"]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "运行代码" }));
    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: "运行状态" }),
      ).toHaveTextContent("运行完成"),
    );
    expect(
      screen.queryByRole("button", { name: "上传截图报错" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("选择错误截图")).not.toBeInTheDocument();
  });

  it("renders extracted_text inline after uploading a screenshot from a failed run", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/lab?view=user-error"]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );
    const uploadButton = await screen.findByRole("button", {
      name: "上传截图报错",
    });
    expect(uploadButton).toBeVisible();

    fetchMock.mockResolvedValueOnce(
      ocrJson({
        extracted_text: "IndexError: list index out of range",
        confidence: 0.91,
        mime: "image/png",
        size_bytes: 0x100,
      }),
    );

    const fileInput = (await screen.findByLabelText(
      "选择错误截图",
    )) as HTMLInputElement;
    await user.upload(fileInput, pngFile());
    await user.click(uploadButton);

    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: "截图识别结果" }),
      ).toHaveTextContent("IndexError: list index out of range"),
    );
    // Optional confidence is surfaced as a percentage.
    expect(screen.getByText(/置信度 91%/)).toBeVisible();
  });

  it("rejects an oversized file client-side and surfaces the 5 MiB rule", async () => {
    // The validator only reads `.type`/`.size`, so a lightweight stub is
    // enough to exercise the cap without allocating a 5 MiB buffer in the
    // test runner. `applyAccept: false` lets us push the stub past the
    // input's accept filter (the real guard is `validateOcrFile`).
    const user = userEvent.setup({ applyAccept: false });
    render(
      <MemoryRouter initialEntries={["/lab?view=user-error"]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );
    const fileInput = (await screen.findByLabelText(
      "选择错误截图",
    )) as HTMLInputElement;
    const oversized = {
      type: "image/png",
      size: 5 * 1024 * 1024 + 1,
      name: "huge.png",
    } as unknown as File;
    await user.upload(fileInput, oversized);
    await user.click(screen.getByRole("button", { name: "上传截图报错" }));

    expect(
      await screen.findByRole("alert", { name: "截图上传失败" }),
    ).toHaveTextContent("5 MiB");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects an unsupported MIME type client-side", async () => {
    // `applyAccept: false` simulates a student picking a non-allowed file via
    // the OS "all files" picker — the real guardrail is the wrapper's
    // `validateOcrFile`, which we exercise here.
    const user = userEvent.setup({ applyAccept: false });
    render(
      <MemoryRouter initialEntries={["/lab?view=user-error"]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );
    const fileInput = (await screen.findByLabelText(
      "选择错误截图",
    )) as HTMLInputElement;
    await user.upload(
      fileInput,
      new File([new Uint8Array(8)], "err.bmp", { type: "image/bmp" }),
    );
    await user.click(screen.getByRole("button", { name: "上传截图报错" }));

    expect(
      await screen.findByRole("alert", { name: "截图上传失败" }),
    ).toHaveTextContent("格式");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("degrades to a copy hint on HTTP 503", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/lab?view=user-error"]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );
    fetchMock.mockResolvedValueOnce(ocrJson({ detail: "busy" }, 503));
    const fileInput = (await screen.findByLabelText(
      "选择错误截图",
    )) as HTMLInputElement;
    await user.upload(fileInput, pngFile());
    await user.click(screen.getByRole("button", { name: "上传截图报错" }));

    expect(
      await screen.findByRole("status", { name: "截图识别不可用" }),
    ).toHaveTextContent("请直接复制错误信息");
  });

  it("retries after a failed OCR attempt with a fresh idempotency key", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/lab?view=user-error"]}>
        <StudentRoutes initialSession={liveStudentSession} />
      </MemoryRouter>,
    );
    fetchMock
      .mockResolvedValueOnce(ocrJson({ detail: "transient" }, 500))
      .mockResolvedValueOnce(
        ocrJson({
          extracted_text: "ValueError: not enough values",
          mime: "image/png",
          size_bytes: 0x40,
        }),
      );
    const fileInput = (await screen.findByLabelText(
      "选择错误截图",
    )) as HTMLInputElement;
    const file = pngFile();
    await user.upload(fileInput, file);
    await user.click(screen.getByRole("button", { name: "上传截图报错" }));
    await screen.findByRole("alert", { name: "截图上传失败" });

    await user.click(screen.getByRole("button", { name: "重试识别" }));

    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: "截图识别结果" }),
      ).toHaveTextContent("ValueError: not enough values"),
    );

    const firstKey = (fetchMock.mock.calls[0]?.[0] as Request).headers.get(
      "Idempotency-Key",
    );
    const retryKey = (fetchMock.mock.calls[1]?.[0] as Request).headers.get(
      "Idempotency-Key",
    );
    expect(firstKey).toMatch(/^ocr-screenshot-/);
    expect(retryKey).toMatch(/^ocr-screenshot-/);
    expect(retryKey).not.toBe(firstKey);
  });
});
