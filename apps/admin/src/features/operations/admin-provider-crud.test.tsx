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

const PROVIDER_ID = "00000000-0000-0000-0000-000000000201";
const PLAINTEXT_KEY = "super-secret-key-1234";

function makeProvider(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    api_key_masked: "••••••••key1",
    created_at: "2026-07-19T02:30:00Z",
    enabled: true,
    endpoint: "https://provider.example.test/v1",
    id: PROVIDER_ID,
    model: "spark-v4",
    params: { temperature: 0.2 },
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
 * Minimal fetch router for the BE-019 provider surface. Each test seeds the
 * responses it needs; unmatched requests throw so a missing branch is loud.
 */
function routerFetch(routes: {
  body?: (request: Request) => unknown;
  GET?: Record<string, () => unknown>;
  POST?: Record<string, (request: Request) => unknown>;
  PATCH?: Record<string, (request: Request) => unknown>;
  DELETE?: Record<string, (request: Request) => unknown>;
}) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const url = request.url;
    const method = request.method.toUpperCase();

    const matchPath = (route: string) => {
      const base = "https://api.example.test/api/v1/admin/providers";
      if (route === "LIST") return url === `${base}` || url === `${base}?`;
      if (route === "TEST")
        return url.startsWith(`${base}/${PROVIDER_ID}/test`);
      if (route === "ENABLE")
        return url.startsWith(`${base}/${PROVIDER_ID}/enable`);
      if (route === "DISABLE")
        return url.startsWith(`${base}/${PROVIDER_ID}/disable`);
      if (route === "DETAIL") return url === `${base}/${PROVIDER_ID}`;
      return url === route;
    };

    const table = (() => {
      switch (method) {
        case "GET":
          return routes.GET;
        case "POST":
          return routes.POST;
        case "PATCH":
          return routes.PATCH;
        case "DELETE":
          return routes.DELETE;
        default:
          return undefined;
      }
    })();
    if (table) {
      const key = Object.keys(table).find((route) => matchPath(route));
      const handler = key ? table[key] : undefined;
      if (key && handler) {
        const body = await handler(request);
        // POST to the collection base creates a resource → 201; everything
        // else (PATCH/DELETE/enable/disable/test) returns 200.
        const status = method === "POST" && key === "LIST" ? 201 : 200;
        return new Response(JSON.stringify(body), {
          headers: { "Content-Type": "application/json" },
          status,
        });
      }
    }
    if (routes.body) {
      const body = await routes.body(request);
      return new Response(JSON.stringify(body), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      });
    }
    throw new Error(`Unexpected ${method} request: ${url}`);
  });
}

async function readBody(request: Request): Promise<Record<string, unknown>> {
  return (await request.clone().json()) as Record<string, unknown>;
}

describe("admin provider CRUD (FE-016)", () => {
  it("creates a provider via POST with Idempotency-Key and never echoes the key", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = routerFetch({
      GET: {
        LIST: () => ({ items: [] }),
      },
      POST: {
        LIST: async (request) => {
          const body = await readBody(request);
          // API key is sent to the backend but must never be rendered back.
          expect(body.api_key).toBe(PLAINTEXT_KEY);
          return makeProvider({
            api_key_masked: "••••••••1234",
            vendor: "newco",
            model: "spark-v4",
            version: 1,
          });
        },
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/providers");

    await screen.findByRole("table", { name: "Provider 配置" });
    await user.click(screen.getByRole("button", { name: "新建 Provider" }));

    const dialog = await screen.findByRole("dialog", { name: "新建 Provider 配置" });
    await user.type(within(dialog).getByLabelText("Vendor"), "newco");
    await user.type(within(dialog).getByLabelText("模型"), "spark-v4");
    await user.selectOptions(within(dialog).getByLabelText("类型"), "LLM");
    await user.type(
      within(dialog).getByLabelText("API Key"),
      PLAINTEXT_KEY,
    );
    await user.type(
      within(dialog).getByLabelText("Endpoint"),
      "https://provider.example.test/v1",
    );

    await user.click(within(dialog).getByRole("button", { name: "保存 Provider" }));

    expect(await screen.findByText("newco")).toBeVisible();
    // The plaintext key must NEVER render in the DOM at any point.
    expect(screen.queryByText(PLAINTEXT_KEY)).not.toBeInTheDocument();

    const createRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find(
        (request) =>
          request.method === "POST" &&
          request.url === "https://api.example.test/api/v1/admin/providers",
      );
    expect(createRequest).toBeTruthy();
    expect(createRequest?.headers.get("Authorization")).toBe("Bearer admin-access");
    expect(createRequest?.headers.get("Idempotency-Key")).toMatch(/^provider-create-/);
    const sent = await readBody(createRequest as Request);
    expect(sent.api_key).toBe(PLAINTEXT_KEY);
    expect(sent.vendor).toBe("newco");
    expect(sent.enabled).toBe(false);
  });

  it("updates a provider via PATCH with Idempotency-Key", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = routerFetch({
      GET: {
        LIST: () => ({ items: [makeProvider({ vendor: "xfyun", model: "spark-v4" })] }),
      },
      PATCH: {
        DETAIL: async (request) => {
          const body = await readBody(request);
          expect(body.model).toBe("spark-v5");
          return makeProvider({ model: "spark-v5", version: 2 });
        },
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/providers");

    await screen.findByText("xfyun");
    await user.click(screen.getByRole("button", { name: "编辑xfyun Provider" }));

    const dialog = await screen.findByRole("dialog", { name: "编辑 Provider 配置" });
    const modelField = within(dialog).getByLabelText("模型");
    await user.clear(modelField);
    await user.type(modelField, "spark-v5");
    await user.click(within(dialog).getByRole("button", { name: "保存 Provider" }));

    // The model is rendered alongside its version (e.g. "spark-v5 · v2"); match
    // against the table cell text to confirm the PATCH result rendered.
    expect(
      await screen.findByText((content) => content.includes("spark-v5")),
    ).toBeVisible();
    expect(screen.queryByText(PLAINTEXT_KEY)).not.toBeInTheDocument();

    const patchRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find((request) => request.method === "PATCH");
    expect(patchRequest?.url).toBe(
      `https://api.example.test/api/v1/admin/providers/${PROVIDER_ID}`,
    );
    expect(patchRequest?.headers.get("Idempotency-Key")).toMatch(/^provider-update-/);
    const sent = await readBody(patchRequest as Request);
    expect(sent.model).toBe("spark-v5");
    // api_key must not be sent when the user did not rotate it.
    expect(sent.api_key).toBeUndefined();
  });

  it("disables an enabled provider via explicit POST /disable", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = routerFetch({
      GET: {
        LIST: () => ({ items: [makeProvider({ enabled: true })] }),
      },
      POST: {
        DISABLE: () => makeProvider({ enabled: false, version: 2 }),
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/providers");

    await screen.findByText("xfyun");
    await user.click(screen.getByRole("button", { name: "停用xfyun Provider" }));

    expect(await screen.findByText(/已停用/)).toBeVisible();
    const disableRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find(
        (request) =>
          request.method === "POST" &&
          request.url ===
            `https://api.example.test/api/v1/admin/providers/${PROVIDER_ID}/disable`,
      );
    expect(disableRequest).toBeTruthy();
    expect(disableRequest?.headers.get("Idempotency-Key")).toMatch(/^provider-disable-/);
  });

  it("enables a disabled provider via explicit POST /enable", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = routerFetch({
      GET: {
        LIST: () => ({ items: [makeProvider({ enabled: false })] }),
      },
      POST: {
        ENABLE: () => makeProvider({ enabled: true, version: 3 }),
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/providers");

    await screen.findByText("xfyun");
    await user.click(screen.getByRole("button", { name: "启用xfyun Provider" }));

    expect(await screen.findByText(/已启用/)).toBeVisible();
    const enableRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find(
        (request) =>
          request.method === "POST" &&
          request.url ===
            `https://api.example.test/api/v1/admin/providers/${PROVIDER_ID}/enable`,
      );
    expect(enableRequest).toBeTruthy();
    expect(enableRequest?.headers.get("Idempotency-Key")).toMatch(/^provider-enable-/);
  });

  it("soft-deletes a provider via DELETE after confirmation", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = routerFetch({
      GET: {
        LIST: () => ({ items: [makeProvider()] }),
      },
      DELETE: {
        DETAIL: () => makeProvider({ enabled: false, version: 4 }),
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/providers");

    await screen.findByText("xfyun");
    await user.click(screen.getByRole("button", { name: "删除xfyun Provider" }));

    const confirm = await screen.findByRole("dialog", { name: "确认删除 Provider" });
    await user.click(within(confirm).getByRole("button", { name: "确认删除" }));

    await waitFor(() => expect(screen.queryByText("xfyun")).not.toBeInTheDocument());
    const deleteRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find((request) => request.method === "DELETE");
    expect(deleteRequest?.url).toBe(
      `https://api.example.test/api/v1/admin/providers/${PROVIDER_ID}`,
    );
    expect(deleteRequest?.headers.get("Idempotency-Key")).toMatch(/^provider-delete-/);
  });

  it("runs the standardized test and renders the BE-019 result fields", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = routerFetch({
      GET: {
        LIST: () => ({ items: [makeProvider({ vendor: "讯飞 LLM" })] }),
      },
      POST: {
        TEST: () => ({
          ok: true,
          latency_ms: 428,
          status_code: 200,
          detail: "reachable",
          model_id: "spark-v4",
          error_code: null,
        }),
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/providers");

    await screen.findByText("讯飞 LLM");
    await user.click(screen.getByRole("button", { name: "测试讯飞 LLM 连通性" }));

    const status = await screen.findByRole("status", { name: "Provider 测试状态" });
    // The standardized BE-019 result must surface model_id and latency_ms in the UI.
    expect(status).toHaveTextContent("428ms");
    expect(status).toHaveTextContent("spark-v4");
    // Plaintext keys must never render.
    expect(screen.queryByText(PLAINTEXT_KEY)).not.toBeInTheDocument();

    const testRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find(
        (request) =>
          request.method === "POST" &&
          request.url ===
            `https://api.example.test/api/v1/admin/providers/${PROVIDER_ID}/test`,
      );
    expect(testRequest?.headers.get("Authorization")).toBe("Bearer admin-access");
  });

  it("tests a candidate api_key via the test dialog without persisting it", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = routerFetch({
      GET: {
        LIST: () => ({ items: [makeProvider({ vendor: "xfyun" })] }),
      },
      POST: {
        TEST: async (request) => {
          const body = await readBody(request);
          // Candidate key reaches the backend test endpoint but is never stored.
          expect(body.api_key).toBe("rotated-candidate-key");
          return {
            ok: true,
            latency_ms: 17,
            status_code: 200,
            detail: "reachable",
            model_id: "spark-v4",
            error_code: null,
          };
        },
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/providers");

    await screen.findByText("xfyun");
    await user.click(screen.getByRole("button", { name: "用候选密钥测试xfyun 连通性" }));

    const dialog = await screen.findByRole("dialog", { name: "测试 Provider 连通性" });
    await user.type(
      within(dialog).getByLabelText("候选 API Key（可选）"),
      "rotated-candidate-key",
    );
    await user.click(within(dialog).getByRole("button", { name: "运行测试" }));

    const status = await screen.findByRole("status", { name: "Provider 测试状态" });
    expect(status).toHaveTextContent("17ms");
    // Candidate key must never render in the DOM.
    expect(screen.queryByText("rotated-candidate-key")).not.toBeInTheDocument();

    const testRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find((request) => request.method === "POST" && request.url.includes("/test"));
    const sent = await readBody(testRequest as Request);
    expect(sent.api_key).toBe("rotated-candidate-key");
  });

  it("never renders a decrypted api_key anywhere in the document", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = routerFetch({
      GET: {
        LIST: () => ({
          items: [
            makeProvider({
              api_key_masked: "••••••••key1",
              vendor: "xfyun",
            }),
          ],
        }),
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAdmin("/admin/providers");

    await screen.findByText("xfyun");
    // The list view must show only the masked form, never plaintext.
    expect(screen.getByText("••••••••key1")).toBeVisible();
    expect(document.body.textContent).not.toContain(PLAINTEXT_KEY);
  });
});
