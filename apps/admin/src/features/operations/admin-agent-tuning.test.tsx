import { render, screen, waitFor, within } from "@testing-library/react";
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

const AGENT_NODES = ["orchestrator", "profile", "path", "resource", "coach", "assessment"] as const;

function currentPublishedBody(node: string, promptText: string) {
  return {
    node,
    version: 3,
    prompt_text: promptText,
    published_at: "2026-07-18T10:00:00Z",
    updated_by: "admin-previous",
    is_published: true,
  };
}

function historyBody(node: string) {
  return {
    items: [
      {
        node,
        version: 3,
        prompt_text: "published prompt body",
        published_at: "2026-07-18T10:00:00Z",
        updated_by: "admin-previous",
        is_current: true,
        is_published: true,
      },
      {
        node,
        version: 2,
        prompt_text: "older published body",
        published_at: "2026-07-10T10:00:00Z",
        updated_by: "admin-old",
        is_current: false,
        is_published: true,
      },
    ],
  };
}

function agentPromptFetchMock(options: {
  node?: string;
  savedVersion?: number;
  savedPrompt?: string;
  dryRunNote?: string;
}) {
  const {
    node = "coach",
    savedVersion = 4,
    savedPrompt = "edited draft prompt",
    dryRunNote = "BE-020 dry-run is not implemented yet; tune via published prompts and replay.",
  } = options;
  return vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const url = request.url;
    // GET current published
    if (
      request.method === "GET" &&
      new RegExp(`/api/v1/admin/agent-prompts/${node}$`).test(url)
    ) {
      return new Response(JSON.stringify(currentPublishedBody(node, "published prompt body")), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      });
    }
    // GET history
    if (
      request.method === "GET" &&
      new RegExp(`/api/v1/admin/agent-prompts/${node}/history$`).test(url)
    ) {
      return new Response(JSON.stringify(historyBody(node)), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      });
    }
    // POST new draft
    if (
      request.method === "POST" &&
      new RegExp(`/api/v1/admin/agent-prompts/${node}$`).test(url)
    ) {
      return new Response(
        JSON.stringify({
          node,
          version: savedVersion,
          prompt_text: savedPrompt,
          updated_by: "admin-001",
          created_at: "2026-07-19T02:30:00Z",
          is_published: false,
        }),
        { headers: { "Content-Type": "application/json" }, status: 201 },
      );
    }
    // POST publish
    if (
      request.method === "POST" &&
      new RegExp(`/api/v1/admin/agent-prompts/${node}/${savedVersion}/publish$`).test(url)
    ) {
      return new Response(
        JSON.stringify({
          node,
          version: savedVersion,
          published_at: "2026-07-19T02:31:00Z",
          updated_by: "admin-001",
          is_published: true,
        }),
        { headers: { "Content-Type": "application/json" }, status: 200 },
      );
    }
    // POST dry-run
    if (
      request.method === "POST" &&
      new RegExp(`/api/v1/admin/agent-prompts/${node}/dry-run$`).test(url)
    ) {
      return new Response(
        JSON.stringify({ implemented: false, note: dryRunNote }),
        { headers: { "Content-Type": "application/json" }, status: 200 },
      );
    }
    throw new Error(`Unexpected request: ${request.method} ${url}`);
  });
}

describe("admin agent tuning UI (FE-017)", () => {
  it("offers all six agent nodes in the node selector", async () => {
    saveServerUrl("https://api.example.test");
    vi.stubGlobal("fetch", agentPromptFetchMock({ node: "orchestrator" }));
    renderAdmin("/admin/agent-tuning");

    const selector = await screen.findByRole("combobox", { name: "Agent 节点" });
    for (const node of AGENT_NODES) {
      expect(within(selector).getByRole("option", { name: node })).toBeInTheDocument();
    }
  });

  it("loads the current published prompt and version history for the selected node", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = agentPromptFetchMock({ node: "coach" });
    vi.stubGlobal("fetch", fetchMock);
    renderAdmin("/admin/agent-tuning");

    const editor = await screen.findByRole("textbox", { name: "提示词草稿" });
    // Draft editor seeds with the published prompt so the admin can edit a known baseline.
    expect(editor).toHaveValue("published prompt body");

    const history = await screen.findByRole("region", { name: "版本历史" });
    expect(within(history).getByText(/v3/)).toBeVisible();
    expect(within(history).getByText(/v2/)).toBeVisible();

    const publishedRegion = screen.getByRole("region", { name: "当前发布版本" });
    expect(publishedRegion).toHaveTextContent("published prompt body");

    // Two GETs (current + history) carry the bearer token.
    const gets = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .filter((request) => request.method === "GET");
    expect(gets.length).toBeGreaterThanOrEqual(2);
    for (const request of gets) {
      expect(request.headers.get("Authorization")).toBe("Bearer admin-access");
    }
  });

  it("saves an edited draft as a new idempotent version and publishes it after confirmation", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = agentPromptFetchMock({
      node: "coach",
      savedVersion: 4,
      savedPrompt: "edited draft prompt",
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/agent-tuning");

    const editor = await screen.findByRole("textbox", { name: "提示词草稿" });
    await user.clear(editor);
    await user.type(editor, "edited draft prompt");

    await user.click(screen.getByRole("button", { name: "保存为新版本" }));

    expect(await screen.findByRole("status", { name: "调优状态" })).toHaveTextContent("已保存草稿 v4");

    await user.click(screen.getByRole("button", { name: "发布版本 v4" }));
    // Confirmation dialog protects the publish action.
    await user.click(screen.getByRole("button", { name: "确认发布" }));
    await waitFor(() =>
      expect(screen.getByRole("status", { name: "调优状态" })).toHaveTextContent("已发布 v4"),
    );

    const saveRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find(
        (request) =>
          request.method === "POST" &&
          new RegExp(`/api/v1/admin/agent-prompts/coach$`).test(request.url),
      );
    expect(saveRequest?.url).toBe("https://api.example.test/api/v1/admin/agent-prompts/coach");
    expect(saveRequest?.headers.get("Authorization")).toBe("Bearer admin-access");
    expect(saveRequest?.headers.get("Idempotency-Key")).toMatch(/^agent-prompt-coach-/);
    await expect(saveRequest?.clone().json()).resolves.toEqual({
      prompt_text: "edited draft prompt",
    });

    const publishRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find(
        (request) =>
          request.method === "POST" &&
          new RegExp(`/api/v1/admin/agent-prompts/coach/4/publish$`).test(request.url),
      );
    expect(publishRequest?.url).toBe(
      "https://api.example.test/api/v1/admin/agent-prompts/coach/4/publish",
    );
    expect(publishRequest?.headers.get("Idempotency-Key")).toMatch(/^agent-prompt-coach-4-publish-/);
  });

  it("relays the BE-020 dry-run note verbatim without faking a result", async () => {
    saveServerUrl("https://api.example.test");
    const note = "BE-020 dry-run not implemented; verify through replay.";
    const fetchMock = agentPromptFetchMock({ node: "assessment", dryRunNote: note });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/agent-tuning");

    // Switch to the assessment node so dry-run targets the right endpoint.
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Agent 节点" }),
      "assessment",
    );
    await screen.findByRole("textbox", { name: "提示词草稿" });

    await user.click(screen.getByRole("button", { name: "试运行" }));

    const status = await screen.findByRole("status", { name: "调优状态" });
    // The backend note must surface verbatim; the UI never invents a fake result.
    expect(status).toHaveTextContent(note);
    expect(status).toHaveTextContent(/未实现|not implemented/i);

    const dryRunRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find(
        (request) =>
          request.method === "POST" &&
          new RegExp(`/api/v1/admin/agent-prompts/assessment/dry-run$`).test(request.url),
      );
    expect(dryRunRequest?.url).toBe(
      "https://api.example.test/api/v1/admin/agent-prompts/assessment/dry-run",
    );
    expect(dryRunRequest?.headers.get("Authorization")).toBe("Bearer admin-access");
  });

  it("rejects non-admin sessions at the admin guard", () => {
    saveServerUrl("https://api.example.test");
    vi.stubGlobal("fetch", agentPromptFetchMock({ node: "coach" }));
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={["/admin/agent-tuning"]}>
          <AdminRoutes
            initialSession={{ ...adminSession, role: "student", accessToken: undefined }}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByRole("alert", { name: "无权访问管理端" })).toBeVisible();
  });
});
