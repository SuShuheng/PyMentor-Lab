import { render, screen, within } from "@testing-library/react";
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

const PROVIDER_ID = "00000000-0000-0000-0000-000000000301";
const PLAINTEXT_KEY = "preset-secret-key-1234";

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
 * Minimal fetch router for the BE-019 provider surface, scoped to FE-016
 * preset needs: list + create. Unmatched requests throw so missing branches
 * are loud.
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

describe("admin provider presets (FE-016)", () => {
  it("renders the apply-preset button when vendor matches a preset (xfyun LLM)", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = routerFetch({
      GET: { LIST: () => ({ items: [] }) },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAdmin("/admin/providers");

    await screen.findByRole("table", { name: "Provider 配置" });
    await screen.findByRole("button", { name: "新建 Provider" });
    (await screen.findByRole("button", { name: "新建 Provider" })).click();

    const dialog = await screen.findByRole("dialog", { name: "新建 Provider 配置" });
    const vendorField = within(dialog).getByLabelText("Vendor");
    await userEvent.type(vendorField, "xfyun");

    // The preset apply button must appear once a preset exists for this vendor.
    expect(
      within(dialog).getByRole("button", { name: "应用预设" }),
    ).toBeInTheDocument();
  });

  it("clicking the preset button fills product/model/endpoint for xfyun LLM", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = routerFetch({
      GET: { LIST: () => ({ items: [] }) },
      POST: {
        LIST: async () => ({
          id: PROVIDER_ID,
          vendor: "xfyun",
          provider_type: "LLM",
          model: "spark-v3.5",
          endpoint: "https://spark-api-open.xf-yun.com/v1",
          api_key_masked: "••••••••3456",
          params: {},
          enabled: false,
          version: 1,
          created_at: "2026-07-19T02:30:00Z",
          updated_at: "2026-07-19T02:30:00Z",
        }),
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/providers");

    await screen.findByRole("table", { name: "Provider 配置" });
    await user.click(screen.getByRole("button", { name: "新建 Provider" }));

    const dialog = await screen.findByRole("dialog", { name: "新建 Provider 配置" });
    await user.type(within(dialog).getByLabelText("Vendor"), "xfyun");
    // Type an API key BEFORE applying preset — it must survive the preset apply.
    await user.type(within(dialog).getByLabelText("API Key"), PLAINTEXT_KEY);

    await user.click(within(dialog).getByRole("button", { name: "应用预设" }));

    // The preset should populate model + endpoint.
    expect(within(dialog).getByLabelText<HTMLInputElement>("模型").value).toBe(
      "spark-v3.5",
    );
    expect(
      within(dialog).getByLabelText<HTMLInputElement>("Endpoint").value,
    ).toContain("spark-api-open.xf-yun.com");
    // The provider_type select should be set to LLM by the preset.
    expect(within(dialog).getByLabelText<HTMLSelectElement>("类型").value).toBe(
      "LLM",
    );

    // API key must NOT be overwritten by the preset.
    expect(within(dialog).getByLabelText<HTMLInputElement>("API Key").value).toBe(
      PLAINTEXT_KEY,
    );

    await user.click(within(dialog).getByRole("button", { name: "保存 Provider" }));

    const createRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find((request) => request.method === "POST");
    expect(createRequest).toBeTruthy();
    const sent = await readBody(createRequest as Request);
    expect(sent.model).toBe("spark-v3.5");
    expect(sent.vendor).toBe("xfyun");
    expect(sent.api_key).toBe(PLAINTEXT_KEY);
  });

  it("does not render the preset button for unknown vendors", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = routerFetch({
      GET: { LIST: () => ({ items: [] }) },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/providers");

    await screen.findByRole("table", { name: "Provider 配置" });
    await user.click(screen.getByRole("button", { name: "新建 Provider" }));

    const dialog = await screen.findByRole("dialog", { name: "新建 Provider 配置" });
    await user.type(within(dialog).getByLabelText("Vendor"), "unknownvendor");

    // No preset button should appear for an unknown vendor.
    expect(
      within(dialog).queryByRole("button", { name: "应用预设" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the form editable after a preset is applied (admin override)", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = routerFetch({
      GET: { LIST: () => ({ items: [] }) },
      POST: {
        LIST: async () => ({
          id: PROVIDER_ID,
          vendor: "openai",
          provider_type: "LLM",
          model: "admin-override-model",
          endpoint: "https://api.openai.com/v1",
          api_key_masked: "••••••••7788",
          params: {},
          enabled: false,
          version: 1,
          created_at: "2026-07-19T02:30:00Z",
          updated_at: "2026-07-19T02:30:00Z",
        }),
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAdmin("/admin/providers");

    await screen.findByRole("table", { name: "Provider 配置" });
    await user.click(screen.getByRole("button", { name: "新建 Provider" }));

    const dialog = await screen.findByRole("dialog", { name: "新建 Provider 配置" });
    await user.type(within(dialog).getByLabelText("Vendor"), "openai");

    await user.click(within(dialog).getByRole("button", { name: "应用预设" }));
    // Preset populated the OpenAI default model.
    const modelField = within(dialog).getByLabelText<HTMLInputElement>("模型");
    expect(modelField.value).toBe("gpt-4o-mini");

    // Admin override: editing the model after preset apply must stick.
    await user.clear(modelField);
    await user.type(modelField, "admin-override-model");
    expect(modelField.value).toBe("admin-override-model");

    await user.type(within(dialog).getByLabelText("API Key"), PLAINTEXT_KEY);
    await user.click(within(dialog).getByRole("button", { name: "保存 Provider" }));

    const createRequest = fetchMock.mock.calls
      .map(([request]) => request as Request)
      .find((request) => request.method === "POST");
    const sent = await readBody(createRequest as Request);
    expect(sent.model).toBe("admin-override-model");
  });
});
