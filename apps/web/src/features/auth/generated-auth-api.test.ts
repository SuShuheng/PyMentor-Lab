import { saveServerUrl } from "@pymentor/config";
import { afterEach, describe, expect, it, vi } from "vitest";

import { browserAuthApi } from "./auth-api";

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("student generated auth API", () => {
  it("logs in through the generated client and resolves the current profile", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "student-access",
            expires_in: 900,
            refresh_token: "student-refresh",
            token_type: "Bearer",
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            display_name: "林晓",
            email: "student@example.edu",
            id: "student-id",
            roles: ["STUDENT"],
            status: "ACTIVE",
            tenant_id: "tenant-id",
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await browserAuthApi.login({
      identifier: "student@example.edu",
      password: "approved-password",
    });

    expect(result).toEqual({
      outcome: "authenticated",
      session: {
        accessToken: "student-access",
        accountStatus: "active",
        displayName: "林晓",
        role: "student",
        userId: "student-id",
      },
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const loginRequest = fetchMock.mock.calls[0]?.[0] as Request;
    const profileRequest = fetchMock.mock.calls[1]?.[0] as Request;
    expect(loginRequest).toBeInstanceOf(Request);
    expect(loginRequest.url).toBe("https://api.example.test/api/v1/auth/login");
    expect(profileRequest.url).toBe("https://api.example.test/api/v1/auth/me");
    expect(profileRequest.headers.get("Authorization")).toBe("Bearer student-access");
  });

  it("registers with the generated contract and reports pending review", async () => {
    saveServerUrl("https://api.example.test/campus");
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          email: "student@example.edu",
          message: "pending review",
          status: "PENDING",
          user_id: "student-id",
        }),
        { headers: { "Content-Type": "application/json" }, status: 201 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      browserAuthApi.register({
        displayName: "林晓",
        email: "student@example.edu",
        password: "approved-password",
        studentId: "S-001",
      }),
    ).resolves.toEqual({ outcome: "pending" });

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.url).toBe("https://api.example.test/campus/api/v1/auth/register");
    await expect(request.clone().json()).resolves.toEqual({
      email: "student@example.edu",
      password: "approved-password",
      student_no: "S-001",
    });
  });

  it.each([
    ["PENDING", { outcome: "pending" }],
    [
      "REJECTED",
      {
        outcome: "rejected",
        reason: "Account is not eligible to login.",
      },
    ],
  ] as const)("preserves %s from a password-verified login denial", async (status, expected) => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          code: "FORBIDDEN",
          details: { account_status: status },
          field_errors: null,
          message: "Account is not eligible to login.",
          retryable: false,
          trace_id: "trc-int002",
        }),
        { headers: { "Content-Type": "application/json" }, status: 403 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      browserAuthApi.login({
        identifier: "student@example.edu",
        password: "approved-password",
      }),
    ).resolves.toEqual(expected);
  });

  it("starts the isolated demo session through the generated endpoint", async () => {
    saveServerUrl("https://api.example.test");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "demo-access",
            expires_in: 900,
            refresh_token: "demo-refresh",
            token_type: "Bearer",
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            display_name: "Demo Guest",
            email: "guest@demo.pymentor.dev",
            id: "demo-user-id",
            roles: ["DEMO_GUEST"],
            status: "ACTIVE",
            tenant_id: "demo-tenant-id",
          }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(browserAuthApi.startDemo()).resolves.toEqual({
      outcome: "authenticated",
      session: {
        accessToken: "demo-access",
        accountStatus: "active",
        displayName: "Demo Guest",
        role: "demo",
        userId: "demo-user-id",
      },
    });

    const demoRequest = fetchMock.mock.calls[0]?.[0] as Request;
    expect(demoRequest.url).toBe("https://api.example.test/api/v1/auth/demo");
    expect(demoRequest.method).toBe("POST");
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

    await expect(browserAuthApi.login({ identifier: "bad", password: "password" })).rejects.toThrow(
      "invalid email",
    );
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
