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
