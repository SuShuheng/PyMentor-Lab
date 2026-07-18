import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { StudentRoutes } from "../../student-routes";
import { studentSession } from "../auth/auth-session";
import { reduceTutorSse } from "./resource-tutor-pages";

function renderStudent(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <StudentRoutes initialSession={studentSession} />
    </MemoryRouter>,
  );
}

describe("progressive learning resources", () => {
  it("renders the fixed five resource types with provenance and review metadata", () => {
    renderStudent("/resources");

    expect(
      screen.getByRole("list", { name: "五类学习资源" }).children,
    ).toHaveLength(5);
    expect(screen.getByRole("article", { name: "微讲义" })).toHaveTextContent(
      "来源 KB-PY-04",
    );
    expect(screen.getByRole("article", { name: "结构卡" })).toHaveTextContent(
      "版本 v2.3",
    );
    expect(screen.getByRole("article", { name: "轨迹动画" })).toHaveTextContent(
      "事实与合规审校通过",
    );
    expect(screen.getByRole("article", { name: "分层练习" })).toBeVisible();
    expect(
      screen.getByRole("article", { name: "Notebook 任务" }),
    ).toBeVisible();
  });

  it("publishes ready resources first and exposes generation progress", () => {
    renderStudent("/resources?view=partial");

    expect(
      screen.getByRole("status", { name: "资源生成进度" }),
    ).toHaveTextContent("3 / 5 已可用");
    expect(screen.getByRole("link", { name: "打开微讲义" })).toHaveAttribute(
      "href",
      "/resources/micro-lecture",
    );
    expect(screen.getByRole("article", { name: "分层练习" })).toHaveTextContent(
      "正在生成",
    );
    expect(
      screen.getByRole("article", { name: "Notebook 任务" }),
    ).toHaveTextContent("等待生成");
  });

  it("uses a safe text fallback and blocks rejected content", () => {
    const { unmount } = renderStudent("/resources?view=fallback");
    expect(screen.getByRole("article", { name: "微讲义" })).toHaveTextContent(
      "配图暂不可用，已切换为审校通过的文字版",
    );

    unmount();
    renderStudent("/resources?view=rejected");
    expect(screen.getByRole("alert")).toHaveTextContent("内容未通过安全审校");
    expect(
      screen.queryByRole("list", { name: "五类学习资源" }),
    ).not.toBeInTheDocument();
  });

  it("opens the micro-lecture as a distinct reviewed learning screen", () => {
    renderStudent("/resources/micro-lecture");

    expect(
      screen.getByRole("heading", { name: "微讲义与知识结构卡" }),
    ).toBeVisible();
    expect(
      screen.getByRole("navigation", { name: "资源内容切换" }),
    ).toBeVisible();
    expect(
      screen.getByRole("article", { name: "微讲义正文" }),
    ).toHaveTextContent("为什么 range 不包含终点？");
    expect(
      screen.getByRole("complementary", { name: "知识结构卡" }),
    ).toHaveTextContent("来源 KB-PY-04");
    expect(
      screen.queryByRole("list", { name: "五类学习资源" }),
    ).not.toBeInTheDocument();
  });
});

describe("tutoring stream", () => {
  it("keeps chunk order, ignores replayed ids, and closes on DONE", () => {
    const first = reduceTutorSse(
      [
        'id: evt-1\ndata: {"choices":[{"delta":{"content":"循环"}}]}',
        'id: evt-2\ndata: {"choices":[{"delta":{"content":"边界"}}]}',
      ].join("\n\n"),
    );
    const resumed = reduceTutorSse(
      [
        'id: evt-2\ndata: {"choices":[{"delta":{"content":"边界"}}]}',
        'id: evt-3\ndata: {"choices":[{"delta":{"content":"要检查 range 的终点。"}}]}',
        "data: [DONE]",
      ].join("\n\n"),
      first,
    );

    expect(resumed.content).toBe("循环边界要检查 range 的终点。");
    expect(resumed.seenEventIds).toEqual(["evt-1", "evt-2", "evt-3"]);
    expect(resumed.done).toBe(true);
  });

  it("separates safe answer, reasoning state, and tool cards without exposing raw reasoning", async () => {
    const user = userEvent.setup();
    renderStudent("/tutor");

    await user.click(screen.getByRole("button", { name: "发送问题" }));
    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: "辅导流状态" }),
      ).toHaveTextContent("回答完成"),
    );

    expect(screen.getByRole("article", { name: "辅导回答" })).toHaveTextContent(
      "range 的右端点不会被取到",
    );
    expect(screen.getByRole("status", { name: "分析状态" })).toHaveTextContent(
      "已完成教学分析",
    );
    expect(
      screen.queryByText("RAW_REASONING_MUST_NOT_RENDER"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("article", { name: "课程知识库检索工具" }),
    ).toHaveTextContent("调用完成");
  });

  it("omits unsupported reasoning and offers an explicit retry after interruption", async () => {
    const plain = renderStudent("/tutor?mode=plain");
    expect(
      screen.queryByRole("status", { name: "分析状态" }),
    ).not.toBeInTheDocument();
    plain.unmount();

    const user = userEvent.setup();
    renderStudent("/tutor?view=retry");
    await user.click(screen.getByRole("button", { name: "发送问题" }));
    await waitFor(() =>
      expect(screen.getByRole("alert", { name: "辅导流中断" })).toBeVisible(),
    );
    await user.click(screen.getByRole("button", { name: "重新连接辅导流" }));
    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: "辅导流状态" }),
      ).toHaveTextContent("回答完成"),
    );
    expect(screen.getByRole("article", { name: "辅导回答" })).toHaveTextContent(
      "不会重复已经收到的片段",
    );
  });
});
