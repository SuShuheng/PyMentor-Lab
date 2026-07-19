import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import { saveServerUrl } from "@pymentor/config";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminRoutes } from "../../admin-routes";
import { adminSession } from "../auth/auth-session";

const liveAdminSession = {
  ...adminSession,
  accessToken: "admin-access",
};

const nodeId = "9512e5ec-f547-51b3-b0df-c5b3a877da9e";
const templateId = "f294238b-386d-58f2-bfd8-3e644b3e329d";

const nodeFixture = {
  node_id: nodeId,
  title: "解释器与交互模式",
  chapter_id: "386d3836-fd6e-5a51-b2a3-0026eabcdac7",
  course_id: "00000000-0000-0000-0000-0000000000a1",
  learning_objectives: ["区分交互命令和脚本执行"],
  prerequisites: [],
  misconceptions: ["终端会自动理解 Python 语法"],
  examples: [">>> 1 + 2"],
  diagnostic_items: [templateId],
  practice_templates: ["9b69a510-f166-5b33-b432-5af0d61e7157"],
  mastery_policy_id: "cd4f1f18-323a-5748-be5b-2838f976951f",
  source_ids: ["6c32b9cb-a61b-58f7-8d11-d4925ffbecfb"],
  content_version: "1.0.0",
  published: false,
  updated_at: "2026-07-19T02:30:00Z",
  audit: {
    last_actor: "course-admin@example.test",
    last_event: "KNOWLEDGE_NODE_UPDATED",
    trace_id: "trace-cms-node",
  },
};

const templateFixture = {
  question_id: templateId,
  node_id: nodeId,
  kind: "MULTIPLE_CHOICE",
  prompt_template: "关于“解释器与交互模式”，哪项分析符合 Python 语义？",
  parameter_schema: {},
  answer_schema: { const: "A", type: "string" },
  test_case_ids: ["df4772f1-d4cd-516c-abad-e7e515a50e17"],
  source_ids: ["6c32b9cb-a61b-58f7-8d11-d4925ffbecfb"],
  content_version: "1.0.0",
  published: false,
  updated_at: "2026-07-19T02:30:00Z",
  audit: {
    last_actor: "course-admin@example.test",
    last_event: "QUESTION_TEMPLATE_UPDATED",
    trace_id: "trace-cms-template",
  },
};

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { gcTime: 0, retry: false, staleTime: 0 },
    },
  });
}

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

function renderAdmin(route: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[route]}>
        <AdminRoutes initialSession={liveAdminSession} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function readBody(request: Request | undefined) {
  if (!request) throw new Error("missing request");
  return request.clone().json();
}

describe("admin CMS node editor (FE-024)", () => {
  it("lists knowledge nodes, edits a node, and PUTs the change with audit", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.method === "GET" && request.url.endsWith(`/api/v1/admin/cms/nodes/${nodeId}`)) {
        return new Response(JSON.stringify(nodeFixture), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      if (request.method === "GET" && request.url.includes("/api/v1/admin/cms/nodes")) {
        return new Response(
          JSON.stringify({
            items: [nodeFixture],
            page: { number: 1, size: 50, total_items: 1, total_pages: 1 },
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.method === "PUT" && request.url.endsWith(`/api/v1/admin/cms/nodes/${nodeId}`)) {
        const body = await request.clone().json();
        return new Response(
          JSON.stringify({ ...nodeFixture, ...body, content_version: "1.0.1", published: false }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      throw new Error(`Unexpected request: ${request.method} ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/cms");

    // List -> search -> open editor
    const list = await screen.findByRole("region", { name: "知识节点浏览" });
    expect(await within(list).findByText("解释器与交互模式")).toBeVisible();
    await user.click(within(list).getByRole("button", { name: "编辑解释器与交互模式" }));

    const editor = await screen.findByRole("region", { name: "节点编辑" });
    expect(within(editor).getByText("1.0.0")).toBeVisible();
    expect(within(editor).getByText(/trace-cms-node/)).toBeVisible();

    // Edit the title and append a learning objective
    const titleField = within(editor).getByLabelText("节点标题");
    await user.clear(titleField);
    await user.type(titleField, "解释器与交互模式（已编辑）");

    const objectivesField = within(editor).getByLabelText("学习目标（每行一条）");
    await user.type(objectivesField, "{Enter}区分 REPL 与脚本入口");

    await user.click(within(editor).getByRole("button", { name: "保存节点" }));

    await waitFor(() =>
      expect(screen.getByRole("status", { name: "节点保存状态" })).toHaveTextContent(
        /已保存.*1\.0\.1/,
      ),
    );

    const putRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find(
        (request) =>
          request.method === "PUT" &&
          request.url === `https://api.example.test/api/v1/admin/cms/nodes/${nodeId}`,
      );
    expect(putRequest).toBeDefined();
    expect(putRequest?.headers.get("Authorization")).toBe("Bearer admin-access");
    expect(putRequest?.headers.get("Idempotency-Key")).toMatch(/^cms-node-/);
    await expect(readBody(putRequest)).resolves.toEqual({
      title: "解释器与交互模式（已编辑）",
      chapter_id: nodeFixture.chapter_id,
      learning_objectives: [
        "区分交互命令和脚本执行",
        "区分 REPL 与脚本入口",
      ],
      prerequisites: nodeFixture.prerequisites,
      misconceptions: nodeFixture.misconceptions,
      examples: nodeFixture.examples,
      diagnostic_items: nodeFixture.diagnostic_items,
      practice_templates: nodeFixture.practice_templates,
      source_ids: nodeFixture.source_ids,
    });
  });

  it("shows server validation errors when PUT is rejected without publishing", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.method === "GET" && request.url.endsWith(`/api/v1/admin/cms/nodes/${nodeId}`)) {
        return new Response(JSON.stringify(nodeFixture), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      if (request.method === "GET" && request.url.includes("/api/v1/admin/cms/nodes")) {
        return new Response(
          JSON.stringify({ items: [nodeFixture], page: { number: 1, size: 50, total_items: 1, total_pages: 1 } }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.method === "PUT" && request.url.endsWith(`/api/v1/admin/cms/nodes/${nodeId}`)) {
        return new Response(
          JSON.stringify({
            detail: [
              { input: "", loc: ["body", "title"], msg: "title must not be empty", type: "value_error" },
            ],
          }),
          { headers: { "Content-Type": "application/json" }, status: 422 },
        );
      }
      throw new Error(`Unexpected request: ${request.method} ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/cms");

    await user.click(
      await screen.findByRole("button", { name: "编辑解释器与交互模式" }),
    );
    const editor = await screen.findByRole("region", { name: "节点编辑" });
    await user.clear(within(editor).getByLabelText("节点标题"));
    await user.click(within(editor).getByRole("button", { name: "保存节点" }));

    const alert = await screen.findByRole("alert", { name: "节点保存错误" });
    expect(alert).toHaveTextContent("title must not be empty");
    // Publish must stay blocked because the latest draft failed validation.
    expect(within(editor).getByRole("button", { name: "发布节点" })).toBeDisabled();

    const publishRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find(
        (request) =>
          request.method === "POST" &&
          request.url === `https://api.example.test/api/v1/admin/cms/nodes/${nodeId}/publish`,
      );
    expect(publishRequest).toBeUndefined();
  });

  it("publishes a node through a confirmation dialog after a successful save", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.method === "GET" && request.url.endsWith(`/api/v1/admin/cms/nodes/${nodeId}`)) {
        return new Response(JSON.stringify(nodeFixture), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      if (request.method === "GET" && request.url.includes("/api/v1/admin/cms/nodes")) {
        return new Response(
          JSON.stringify({ items: [nodeFixture], page: { number: 1, size: 50, total_items: 1, total_pages: 1 } }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (request.method === "PUT" && request.url.endsWith(`/api/v1/admin/cms/nodes/${nodeId}`)) {
        return new Response(
          JSON.stringify({ ...nodeFixture, content_version: "1.0.1" }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      if (
        request.method === "POST" &&
        request.url.endsWith(`/api/v1/admin/cms/nodes/${nodeId}/publish`)
      ) {
        return new Response(
          JSON.stringify({ ...nodeFixture, content_version: "1.0.1", published: true }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      throw new Error(`Unexpected request: ${request.method} ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/cms");

    await user.click(
      await screen.findByRole("button", { name: "编辑解释器与交互模式" }),
    );
    const editor = await screen.findByRole("region", { name: "节点编辑" });
    await user.click(within(editor).getByRole("button", { name: "保存节点" }));
    await screen.findByRole("status", { name: "节点保存状态" });

    await user.click(within(editor).getByRole("button", { name: "发布节点" }));
    const dialog = await screen.findByRole("dialog", { name: "确认发布节点" });
    await user.click(within(dialog).getByRole("button", { name: "确认发布" }));

    await waitFor(() =>
      expect(screen.getByRole("status", { name: "节点保存状态" })).toHaveTextContent("已发布"),
    );

    const publishRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find(
        (request) =>
          request.method === "POST" &&
          request.url === `https://api.example.test/api/v1/admin/cms/nodes/${nodeId}/publish`,
      );
    expect(publishRequest).toBeDefined();
    expect(publishRequest?.headers.get("Authorization")).toBe("Bearer admin-access");
    expect(publishRequest?.headers.get("Idempotency-Key")).toMatch(/^cms-node-publish-/);
  });

  it("PUTs a question template with an edited prompt and JSON answer_schema", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (
        request.method === "GET" &&
        request.url.endsWith(`/api/v1/admin/cms/question_templates/${templateId}`)
      ) {
        return new Response(JSON.stringify(templateFixture), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }
      if (
        request.method === "PUT" &&
        request.url.endsWith(`/api/v1/admin/cms/question_templates/${templateId}`)
      ) {
        const body = await request.clone().json();
        return new Response(
          JSON.stringify({ ...templateFixture, ...body, content_version: "1.0.1" }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }
      throw new Error(`Unexpected request: ${request.method} ${request.url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin(`/admin/cms/question_templates/${templateId}`);

    const editor = await screen.findByRole("region", { name: "题目模板编辑" });
    expect(within(editor).getByText(/trace-cms-template/)).toBeVisible();
    const promptField = within(editor).getByLabelText("题目 prompt 模板");
    await user.type(promptField, "（已更新）");
    const answerField = within(editor).getByLabelText(
      "answer_schema (JSON)",
    ) as HTMLTextAreaElement;
    // userEvent.type interprets `{` as a keyboard modifier, so drive the JSON
    // textarea through fireEvent.change — the behaviour under test is the
    // shape of the PUT body, not the keystroke timing.
    fireEvent.change(answerField, {
      target: { value: '{"type":"string","const":"B"}' },
    });

    await user.click(within(editor).getByRole("button", { name: "保存题目模板" }));
    await waitFor(() =>
      expect(screen.getByRole("status", { name: "题目模板保存状态" })).toHaveTextContent(
        /已保存.*1\.0\.1/,
      ),
    );

    const putRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find(
        (request) =>
          request.method === "PUT" &&
          request.url ===
            `https://api.example.test/api/v1/admin/cms/question_templates/${templateId}`,
      );
    expect(putRequest).toBeDefined();
    expect(putRequest?.headers.get("Idempotency-Key")).toMatch(/^cms-question-/);
    await expect(readBody(putRequest)).resolves.toEqual({
      kind: templateFixture.kind,
      prompt_template: `${templateFixture.prompt_template}（已更新）`,
      parameter_schema: templateFixture.parameter_schema,
      answer_schema: { const: "B", type: "string" },
      test_case_ids: templateFixture.test_case_ids,
      source_ids: templateFixture.source_ids,
    });
  });
});
