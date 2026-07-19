import * as publicApi from "./index";
import {
  client,
  demoLoginApiV1AuthDemoPost,
  loginApiV1AuthLoginPost,
  type HttpValidationError,
} from "./index";
import { describe, expect, it, vi } from "vitest";

describe("generated runtime client", () => {
  it("exports the fetch client and callable auth SDK operations", () => {
    expect(publicApi).toHaveProperty("client");
    expect(publicApi).toHaveProperty("demoLoginApiV1AuthDemoPost");
    expect(publicApi).toHaveProperty("loginApiV1AuthLoginPost");
    expect(typeof demoLoginApiV1AuthDemoPost).toBe("function");
    expect(typeof Reflect.get(publicApi, "loginApiV1AuthLoginPost")).toBe(
      "function",
    );
  });

  it("uses renderer base URL and credentials and returns typed data", async () => {
    const fetchMock = vi.fn(async (_request: Request) =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            access_token: "access-token",
            expires_in: 900,
            refresh_token: "refresh-token",
            token_type: "Bearer",
          }),
          {
            headers: { "Content-Type": "application/json" },
            status: 200,
          },
        ),
      ),
    );
    client.setConfig({
      baseUrl: "https://api.example.test",
      credentials: "include",
      fetch: fetchMock,
    });

    const result = await loginApiV1AuthLoginPost({
      body: { email: "student@example.test", password: "secret123" },
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const request = fetchMock.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request?.url).toBe("https://api.example.test/api/v1/auth/login");
    expect(request?.credentials).toBe("include");
    await expect(request?.clone().json()).resolves.toEqual({
      email: "student@example.test",
      password: "secret123",
    });
    expect(result.data?.access_token).toBe("access-token");
    expect(result.error).toBeUndefined();
  });

  it("returns generated typed errors without throwing by default", async () => {
    const validationError: HttpValidationError = {
      detail: [
        {
          input: "bad",
          loc: ["body", "email"],
          msg: "invalid email",
          type: "value_error",
        },
      ],
    };
    client.setConfig({
      baseUrl: "https://api.example.test",
      fetch: vi.fn(async () =>
        Promise.resolve(
          new Response(JSON.stringify(validationError), {
            headers: { "Content-Type": "application/json" },
            status: 422,
          }),
        ),
      ),
    });

    const result = await loginApiV1AuthLoginPost({
      body: { email: "bad", password: "secret123" },
    });

    expect(result.data).toBeUndefined();
    expect(result.error).toEqual(validationError);
    expect(result.response.status).toBe(422);
  });
});
