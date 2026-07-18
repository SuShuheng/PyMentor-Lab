import {
  client,
  loginApiV1AuthLoginPost,
  meApiV1AuthMeGet,
  refreshApiV1AuthRefreshPost,
  type AuthTokens,
  type UserProfile,
} from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";

export type AuthSession = {
  accessToken?: string;
  displayName: string;
  role: "admin" | "demo" | "student";
  userId: string;
};

export const adminSession: AuthSession = {
  displayName: "系统管理员",
  role: "admin",
  userId: "admin-001",
};

export const studentSession: AuthSession = {
  displayName: "林小满",
  role: "student",
  userId: "student-001",
};

export type AuthResult = { session: AuthSession } | { session: null };

export type AdminAuthApi = {
  login(input: { identifier: string; password: string }): Promise<AuthResult>;
  refresh(): Promise<AuthResult>;
};

let refreshToken: string | null = null;

function configureClient(): void {
  client.setConfig({
    baseUrl: readServerUrl(),
    credentials: "include",
    fetch,
  });
}

function errorDetail(error: unknown): string | undefined {
  if (!error || typeof error !== "object") return undefined;
  const detail = Reflect.get(error, "detail");
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return undefined;
  const messages = detail
    .map((entry) =>
      entry && typeof entry === "object" && typeof Reflect.get(entry, "msg") === "string"
        ? String(Reflect.get(entry, "msg"))
        : null,
    )
    .filter((message): message is string => message !== null);
  return messages.length > 0 ? messages.join("；") : undefined;
}

function throwApiError(error: unknown): never {
  throw new Error(errorDetail(error) ?? "管理员登录失败");
}

function roleFromProfile(profile: UserProfile): AuthSession["role"] {
  if (profile.roles?.some((role) => ["SYSTEM_ADMIN", "TENANT_ADMIN", "admin"].includes(role))) {
    return "admin";
  }
  if (profile.roles?.some((role) => ["DEMO", "demo"].includes(role))) {
    return "demo";
  }
  return "student";
}

async function resolveSession(tokens: AuthTokens): Promise<AuthResult> {
  refreshToken = tokens.refresh_token;
  const profileResult = await meApiV1AuthMeGet({
    headers: { Authorization: `Bearer ${tokens.access_token}` },
  });
  if (profileResult.response.status === 401) return { session: null };
  if (!profileResult.data) throwApiError(profileResult.error);
  const profile = profileResult.data;
  if (profile.status !== "ACTIVE") return { session: null };
  return {
    session: {
      accessToken: tokens.access_token,
      displayName: profile.display_name ?? profile.email,
      role: roleFromProfile(profile),
      userId: profile.id,
    },
  };
}

export const browserAdminAuthApi: AdminAuthApi = {
  login: async (input) => {
    configureClient();
    const result = await loginApiV1AuthLoginPost({
      body: { email: input.identifier, password: input.password },
    });
    if (result.response.status === 401 || result.response.status === 403) {
      return { session: null };
    }
    if (!result.data) throwApiError(result.error);
    return resolveSession(result.data);
  },
  refresh: async () => {
    if (!refreshToken) return { session: null };
    configureClient();
    const result = await refreshApiV1AuthRefreshPost({
      body: { refresh_token: refreshToken },
    });
    if (result.response.status === 401) {
      refreshToken = null;
      return { session: null };
    }
    if (!result.data) throwApiError(result.error);
    return resolveSession(result.data);
  },
};
