import { saveServerUrl } from "@pymentor/config";
import { afterEach, describe, expect, it, vi } from "vitest";

import { browserAdminAuthApi } from "./auth-api";

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("admin generated auth API", () => {
  it("logs in through the generated client and resolves the admin profile", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "admin-access",
            expires_in: 900,
            refresh_token: "admin-refresh",
            token_type: "Bearer",
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            display_name: "系统管理员",
            email: "admin@example.edu",
            id: "admin-id",
            roles: ["SYSTEM_ADMIN"],
            status: "ACTIVE",
            tenant_id: "tenant-id",
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await browserAdminAuthApi.login({
      identifier: "admin@example.edu",
      password: "approved-password",
    });

    expect(result).toEqual({
      session: {
        accessToken: "admin-access",
        displayName: "系统管理员",
        role: "admin",
        userId: "admin-id",
      },
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const loginRequest = fetchMock.mock.calls[0]?.[0] as Request;
    const profileRequest = fetchMock.mock.calls[1]?.[0] as Request;
    expect(loginRequest).toBeInstanceOf(Request);
    expect(loginRequest.url).toBe("https://api.example.test/api/v1/auth/login");
    expect(profileRequest.url).toBe("https://api.example.test/api/v1/auth/me");
    expect(profileRequest.headers.get("Authorization")).toBe("Bearer admin-access");
  });

  it("surfaces generated validation errors without inventing a session", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: [
            {
              input: "bad",
              loc: ["body", "email"],
              msg: "invalid email",
              type: "value_error",
            },
          ],
        }),
        { headers: { "Content-Type": "application/json" }, status: 422 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      browserAdminAuthApi.login({ identifier: "bad", password: "password" }),
    ).rejects.toThrow("invalid email");
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
