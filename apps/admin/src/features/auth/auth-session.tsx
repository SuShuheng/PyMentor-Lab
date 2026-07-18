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

type AuthResult = { session: AuthSession } | { session: null };

export type AdminAuthApi = {
  login(input: { identifier: string; password: string }): Promise<AuthResult>;
  refresh(): Promise<AuthResult>;
};

async function postAuth(path: string, body?: unknown): Promise<AuthResult> {
  const response = await fetch(`${readServerUrl()}${path}`, {
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "include",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    method: "POST",
  });
  if (response.status === 401) return { session: null };

  const payload = (await response.json().catch(() => ({}))) as Record<
    string,
    unknown
  >;
  if (!response.ok) {
    throw new Error(
      typeof payload.detail === "string" ? payload.detail : "管理员登录失败",
    );
  }
  const user = (payload.user ?? payload) as Record<string, unknown>;
  return {
    session: {
      accessToken:
        typeof payload.access_token === "string"
          ? payload.access_token
          : undefined,
      displayName:
        typeof user.display_name === "string" ? user.display_name : "管理员",
      role:
        user.role === "admin"
          ? "admin"
          : user.role === "demo"
            ? "demo"
            : "student",
      userId: typeof user.id === "string" ? user.id : "current-user",
    },
  };
}

const browserAdminAuthApi: AdminAuthApi = {
  login: (input) => postAuth("/auth/login", input),
  refresh: () => postAuth("/auth/refresh"),
};

type AuthContextValue = {
  errorMessage: string | null;
  login(input: { identifier: string; password: string }): Promise<void>;
  refresh(): Promise<void>;
  session: AuthSession | null;
  status:
    | "anonymous"
    | "authenticated"
    | "checking"
    | "error"
    | "refresh-failed";
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AdminAuthProvider({
  api = browserAdminAuthApi,
  children,
  initialSession,
}: {
  api?: AdminAuthApi;
  children: ReactNode;
  initialSession?: AuthSession | null;
}) {
  const [session, setSession] = useState<AuthSession | null>(
    initialSession ?? null,
  );
  const [status, setStatus] = useState<AuthContextValue["status"]>(() =>
    initialSession === undefined
      ? "checking"
      : initialSession
        ? "authenticated"
        : "anonymous",
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const applyResult = useCallback((result: AuthResult) => {
    setSession(result.session);
    setStatus(result.session ? "authenticated" : "anonymous");
    setErrorMessage(null);
  }, []);

  const refresh = useCallback(async () => {
    setStatus("checking");
    try {
      applyResult(await api.refresh());
    } catch {
      setSession(null);
      setStatus("refresh-failed");
      setErrorMessage("会话刷新失败，请检查服务器连接");
    }
  }, [api, applyResult]);

  useEffect(() => {
    if (initialSession === undefined) void refresh();
  }, [initialSession, refresh]);

  const value = useMemo<AuthContextValue>(
    () => ({
      errorMessage,
      login: async (input) => {
        setStatus("checking");
        setErrorMessage(null);
        try {
          applyResult(await api.login(input));
        } catch (error) {
          setSession(null);
          setStatus("error");
          setErrorMessage(
            error instanceof Error ? error.message : "管理员登录失败",
          );
        }
      },
      refresh,
      session,
      status,
    }),
    [api, applyResult, errorMessage, refresh, session, status],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAdminAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value)
    throw new Error("useAdminAuth must be used within AdminAuthProvider");
  return value;
}
