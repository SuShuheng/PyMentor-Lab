import { readServerUrl } from "@pymentor/config";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

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

type AuthStatus =
  | "anonymous"
  | "authenticated"
  | "checking"
  | "error"
  | "pending"
  | "refresh-failed"
  | "rejected";

type AuthContextValue = {
  clearOutcome(): void;
  errorMessage: string | null;
  login(input: { identifier: string; password: string }): Promise<void>;
  refresh(): Promise<void>;
  register(input: {
    displayName: string;
    email: string;
    password: string;
    studentId: string;
  }): Promise<void>;
  session: AuthSession | null;
  startDemo(): Promise<void>;
  status: AuthStatus;
};

async function postAuth(path: string, body?: unknown): Promise<AuthResult> {
  const response = await fetch(`${readServerUrl()}${path}`, {
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "include",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    method: "POST",
  });

  const payload = (await response.json().catch(() => ({}))) as Record<
    string,
    unknown
  >;
  if (response.status === 202 || payload.account_status === "PENDING")
    return { outcome: "pending" };
  if (response.status === 403 && payload.account_status === "REJECTED") {
    return {
      outcome: "rejected",
      reason: typeof payload.detail === "string" ? payload.detail : undefined,
    };
  }
  if (response.status === 401) return { outcome: "unauthenticated" };
  if (!response.ok) {
    throw new Error(
      typeof payload.detail === "string"
        ? payload.detail
        : "请求失败，请稍后重试",
    );
  }

  const user = (payload.user ?? payload) as Record<string, unknown>;
  return {
    outcome: "authenticated",
    session: {
      accessToken:
        typeof payload.access_token === "string"
          ? payload.access_token
          : undefined,
      accountStatus: "active",
      displayName:
        typeof user.display_name === "string" ? user.display_name : "学习者",
      role:
        user.role === "admin" || user.role === "demo" ? user.role : "student",
      userId: typeof user.id === "string" ? user.id : "current-user",
    },
  };
}

export const browserAuthApi: AuthApi = {
  login: (input) => postAuth("/auth/login", input),
  refresh: () => postAuth("/auth/refresh"),
  register: (input) => postAuth("/auth/register", input),
  startDemo: () => postAuth("/auth/demo"),
};

const AuthContext = createContext<AuthContextValue | null>(null);

function statusFromResult(
  result: AuthResult,
): Exclude<AuthStatus, "checking" | "error" | "refresh-failed"> {
  if (result.outcome === "authenticated") return "authenticated";
  if (result.outcome === "pending") return "pending";
  if (result.outcome === "rejected") return "rejected";
  return "anonymous";
}

export function AuthProvider({
  api = browserAuthApi,
  children,
  initialSession,
}: {
  api?: AuthApi;
  children: ReactNode;
  initialSession?: AuthSession | null;
}) {
  const [session, setSession] = useState<AuthSession | null>(
    initialSession ?? null,
  );
  const [status, setStatus] = useState<AuthStatus>(() =>
    initialSession === undefined
      ? "checking"
      : initialSession
        ? "authenticated"
        : "anonymous",
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const applyResult = useCallback((result: AuthResult) => {
    setSession(result.outcome === "authenticated" ? result.session : null);
    setStatus(statusFromResult(result));
    setErrorMessage(
      result.outcome === "rejected" ? (result.reason ?? null) : null,
    );
  }, []);

  const refresh = useCallback(async () => {
    setStatus("checking");
    setErrorMessage(null);
    try {
      applyResult(await api.refresh());
    } catch {
      setSession(null);
      setStatus("refresh-failed");
      setErrorMessage("会话刷新失败，请检查服务器连接后重试");
    }
  }, [api, applyResult]);

  useEffect(() => {
    if (initialSession === undefined) void refresh();
  }, [initialSession, refresh]);

  const run = useCallback(
    async (request: () => Promise<AuthResult>) => {
      setStatus("checking");
      setErrorMessage(null);
      try {
        applyResult(await request());
      } catch (error) {
        setSession(null);
        setStatus("error");
        setErrorMessage(
          error instanceof Error ? error.message : "请求失败，请稍后重试",
        );
      }
    },
    [applyResult],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      clearOutcome: () => {
        setStatus("anonymous");
        setErrorMessage(null);
      },
      errorMessage,
      login: (input) => run(() => api.login(input)),
      refresh,
      register: (input) => run(() => api.register(input)),
      session,
      startDemo: () => run(() => api.startDemo()),
      status,
    }),
    [api, errorMessage, refresh, run, session, status],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}
