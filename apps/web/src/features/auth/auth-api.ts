import {
  client,
  demoLoginApiV1AuthDemoPost,
  loginApiV1AuthLoginPost,
  meApiV1AuthMeGet,
  refreshApiV1AuthRefreshPost,
  registerApiV1AuthRegisterPost,
  type AuthTokens,
  type UserProfile,
} from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";

export type AuthRole = "admin" | "demo" | "student";

export type AuthSession = {
  accessToken?: string;
  accountStatus: "active";
  displayName: string;
  role: AuthRole;
  userId: string;
};

export type AuthResult =
  | { outcome: "authenticated"; session: AuthSession }
  | { outcome: "pending" }
  | { outcome: "rejected"; reason?: string }
  | { outcome: "unauthenticated" };

export type AuthApi = {
  login(input: { identifier: string; password: string }): Promise<AuthResult>;
  refresh(): Promise<AuthResult>;
  register(input: {
    displayName: string;
    email: string;
    password: string;
    studentId: string;
  }): Promise<AuthResult>;
  startDemo(): Promise<AuthResult>;
};

export const studentSession: AuthSession = {
  accountStatus: "active",
  displayName: "林小满",
  role: "student",
  userId: "student-001",
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
  throw new Error(errorDetail(error) ?? "请求失败，请稍后重试");
}

function roleFromProfile(profile: UserProfile): AuthRole {
  if (
    profile.roles?.some((role) =>
      ["SYSTEM_ADMIN", "COURSE_ADMIN", "REVIEWER", "TENANT_ADMIN", "admin"].includes(role),
    )
  ) {
    return "admin";
  }
  if (profile.roles?.some((role) => ["DEMO_GUEST", "DEMO", "demo"].includes(role))) {
    return "demo";
  }
  return "student";
}

function outcomeFromProfile(profile: UserProfile, accessToken: string): AuthResult {
  if (profile.status === "PENDING") return { outcome: "pending" };
  if (profile.status === "REJECTED") return { outcome: "rejected" };
  if (profile.status !== "ACTIVE") return { outcome: "unauthenticated" };
  return {
    outcome: "authenticated",
    session: {
      accessToken,
      accountStatus: "active",
      displayName: profile.display_name ?? profile.email,
      role: roleFromProfile(profile),
      userId: profile.id,
    },
  };
}

async function resolveSession(tokens: AuthTokens): Promise<AuthResult> {
  refreshToken = tokens.refresh_token;
  const profileResult = await meApiV1AuthMeGet({
    headers: { Authorization: `Bearer ${tokens.access_token}` },
  });
  if (profileResult.response.status === 401) return { outcome: "unauthenticated" };
  if (!profileResult.data) throwApiError(profileResult.error);
  return outcomeFromProfile(profileResult.data, tokens.access_token);
}

export const browserAuthApi: AuthApi = {
  login: async (input) => {
    configureClient();
    const result = await loginApiV1AuthLoginPost({
      body: { email: input.identifier, password: input.password },
    });
    if (result.response.status === 401) return { outcome: "unauthenticated" };
    if (result.response.status === 403) {
      return { outcome: "rejected", reason: errorDetail(result.error) };
    }
    if (!result.data) throwApiError(result.error);
    return resolveSession(result.data);
  },
  refresh: async () => {
    if (!refreshToken) return { outcome: "unauthenticated" };
    configureClient();
    const result = await refreshApiV1AuthRefreshPost({
      body: { refresh_token: refreshToken },
    });
    if (result.response.status === 401) {
      refreshToken = null;
      return { outcome: "unauthenticated" };
    }
    if (!result.data) throwApiError(result.error);
    return resolveSession(result.data);
  },
  register: async (input) => {
    configureClient();
    const result = await registerApiV1AuthRegisterPost({
      body: {
        email: input.email,
        password: input.password,
        student_no: input.studentId || null,
      },
    });
    if (!result.data) throwApiError(result.error);
    return { outcome: "pending" };
  },
  startDemo: async () => {
    configureClient();
    const result = await demoLoginApiV1AuthDemoPost();
    if (!result.data) throwApiError(result.error);
    return resolveSession(result.data);
  },
};
