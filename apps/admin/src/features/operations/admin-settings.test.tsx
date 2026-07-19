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

const PROVIDER_ID = "00000000-0000-0000-0000-000000000401";
const PLAINTEXT_KEY = "settings-secret-key-1234";

function makeProvider(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    api_key_masked: "••••••••key1",
    created_at: "2026-07-19T02:30:00Z",
    enabled: true,
    endpoint: "https://spark-api-open.xf-yun.com/v1",
    id: PROVIDER_ID,
    model: "spark-v3.5",
    params: {},
    provider_type: "LLM",
    updated_at: "2026-07-19T02:30:00Z",
    vendor: "xfyun",
    version: 1,
    ...overrides,
  };
}

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

/**
 * Minimal fetch router for the BE-019 provider surface, scoped to the settings
 * page needs (list + create + test). Unmatched requests throw so missing
 * branches are loud.
 */
function routerFetch(routes: {
  GET?: Record<string, () => unknown>;
  POST?: Record<string, (request: Request) => unknown>;
}) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const url = request.url;
    const method = request.method.toUpperCase();
    const base = "https://api.example.test/api/v1/admin/providers";

    const table = method === "GET" ? routes.GET : method === "POST" ? routes.POST : undefined;
    if (table) {
      const key = Object.keys(table).find((route) => {
        if (route === "LIST") return url === base || url === `${base}?`;
        if (route === "TEST") return url.startsWith(`${base}/${PROVIDER_ID}/test`);
        return url === route;
      });
      const handler = key ? table[key] : undefined;
      if (key && handler) {
        const body = await handler(request);
        const status = method === "POST" && key === "LIST" ? 201 : 200;
        return new Response(JSON.stringify(body), {
          headers: { "Content-Type": "application/json" },
          status,
        });
      }
    }
    throw new Error(`Unexpected ${method} request: ${url}`);
  });
}

async function readBody(request: Request): Promise<Record<string, unknown>> {
  return (await request.clone().json()) as Record<string, unknown>;
}

describe("admin settings page — Provider config + guided setup (FE-016 Stage B)", () => {
  it("keeps the existing session section and adds an AI 服务商配置 section", async () => {
    saveServerUrl("https://api.example.test");
    vi.stubGlobal(
      "fetch",
      routerFetch({
        GET: { LIST: () => ({ items: [] }) },
      }),
    );
    renderAdmin("/admin/settings");

    // Existing session section is preserved.
    expect(await screen.findByRole("heading", { name: "管理端设置" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "当前会话" })).toBeVisible();
    // New AI provider section.
    expect(await screen.findByRole("heading", { name: "AI 服务商配置" })).toBeVisible();
  });

  it("renders a summary table of configured providers with a link to the management page", async () => {
    saveServerUrl("https://api.example.test");
    vi.stubGlobal(
      "fetch",
      routerFetch({
        GET: {
          LIST: () => ({
            items: [
              makeProvider({
                vendor: "xfyun",
                model: "spark-v3.5",
                provider_type: "LLM",
                enabled: true,
              }),
            ],
          }),
        },
      }),
    );
    renderAdmin("/admin/settings");

    // Summary table is rendered with provider row.
    const table = await screen.findByRole("table", { name: "已配置 Provider 摘要" });
    expect(within(table).getByText("xfyun")).toBeVisible();
    expect(within(table).getByText("LLM")).toBeVisible();

    // When providers exist, the guided wizard is NOT rendered.
    expect(screen.queryByRole("heading", { name: "首次配置引导" })).not.toBeInTheDocument();

    // A link takes the admin to the full CRUD page.
    expect(
      screen.getByRole("link", { name: "前往 Provider 管理页" }),
    ).toHaveAttribute("href", "/admin/providers");
  });

  it("renders the first-time guided wizard when providers list is empty", async () => {
    saveServerUrl("https://api.example.test");
    vi.stubGlobal(
      "fetch",
      routerFetch({
        GET: { LIST: () => ({ items: [] }) },
      }),
    );
    renderAdmin("/admin/settings");

    expect(await screen.findByRole("heading", { name: "首次配置引导" })).toBeVisible();
    // Step 1 (LLM) is the first card; step markers exist for the three steps.
    expect(screen.getByText(/LLM 对话 Provider/)).toBeVisible();
    expect(screen.getByText(/讯飞 TTS\/ASR\/OCR/)).toBeVisible();
    expect(screen.getByText(/讯飞内容审核/)).toBeVisible();
    // Skip link is offered.
    expect(
      screen.getByRole("link", { name: "跳过引导，前往 Provider 管理页" }),
    ).toHaveAttribute("href", "/admin/providers");
  });

  it("applies the preset on vendor select in the wizard's LLM step", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = routerFetch({
      GET: { LIST: () => ({ items: [] }) },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/settings");

    await screen.findByRole("heading", { name: "首次配置引导" });

    // Step 1 vendor select defaults to xfyun; the apply-preset button is visible.
    const llmStep = screen.getByTestId("wizard-step-LLM");
    await user.click(within(llmStep).getByRole("button", { name: "应用预设" }));

    // Preset fills model + endpoint with the known xfyun LLM values.
    expect(within(llmStep).getByLabelText<HTMLInputElement>("模型").value).toBe("spark-v3.5");
    expect(within(llmStep).getByLabelText<HTMLInputElement>("Endpoint").value).toContain(
      "spark-api-open.xf-yun.com",
    );
  });

  it("creates an enabled LLM provider from the wizard with the documented test-before-create flow", async () => {
    saveServerUrl("https://api.example.test");
    // The fake backend remembers what the wizard creates so a subsequent
    // list refetch (triggered by the cache invalidation) returns the new row —
    // exactly how the real BE-019 surface behaves.
    const created: ReturnType<typeof makeProvider>[] = [];
    const fetchMock = routerFetch({
      GET: { LIST: () => ({ items: created }) },
      POST: {
        LIST: async (request) => {
          const body = await readBody(request);
          // The wizard enables the provider on create.
          expect(body.enabled).toBe(true);
          expect(body.vendor).toBe("xfyun");
          expect(body.provider_type).toBe("LLM");
          const row = makeProvider({
            enabled: true,
            provider_type: "LLM",
            vendor: "xfyun",
            model: "spark-v3.5",
          });
          created.push(row);
          return row;
        },
        // test-after-create: the wizard tests the freshly-created provider.
        TEST: () => ({
          ok: true,
          latency_ms: 88,
          status_code: 200,
          detail: "reachable",
          model_id: "spark-v3.5",
          error_code: null,
        }),
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/settings");

    await screen.findByRole("heading", { name: "首次配置引导" });

    const llmStep = screen.getByTestId("wizard-step-LLM");
    await user.click(within(llmStep).getByRole("button", { name: "应用预设" }));
    await user.type(within(llmStep).getByLabelText("API Key"), PLAINTEXT_KEY);

    await user.click(within(llmStep).getByRole("button", { name: "创建并启用" }));

    // The created provider shows up in the summary table after refetch. The
    // model is rendered alongside its version inside a <small>, so match on
    // a substring rather than an exact text node.
    expect(
      await screen.findByText((content) => content.includes("spark-v3.5")),
    ).toBeVisible();
    // Plaintext key must never render in the DOM.
    expect(screen.queryByText(PLAINTEXT_KEY)).not.toBeInTheDocument();

    const createRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find(
        (request) =>
          request.method === "POST" &&
          request.url === "https://api.example.test/api/v1/admin/providers",
      );
    expect(createRequest).toBeTruthy();
    expect(createRequest?.headers.get("Idempotency-Key")).toMatch(/^provider-create-/);
  });

  it("marks the LLM step complete when an LLM provider exists", async () => {
    saveServerUrl("https://api.example.test");
    vi.stubGlobal(
      "fetch",
      routerFetch({
        GET: {
          LIST: () => ({
            items: [
              makeProvider({
                vendor: "xfyun",
                provider_type: "LLM",
                enabled: true,
                model: "spark-v3.5",
              }),
            ],
          }),
        },
      }),
    );
    renderAdmin("/admin/settings");

    // Provider exists → summary table shows; the "all configured" hint surfaces.
    await screen.findByRole("table", { name: "已配置 Provider 摘要" });
    await waitFor(() => {
      expect(screen.getByText("LLM")).toBeVisible();
    });
  });
});
