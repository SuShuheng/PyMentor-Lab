import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { browserAuthApi, type AuthApi, type AuthResult, type AuthSession } from "./auth-api";

export {
  browserAuthApi,
  studentSession,
  type AuthApi,
  type AuthResult,
  type AuthRole,
  type AuthSession,
} from "./auth-api";

type AuthStatus =
  "anonymous" | "authenticated" | "checking" | "error" | "pending" | "refresh-failed" | "rejected";

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
  const [session, setSession] = useState<AuthSession | null>(initialSession ?? null);
  const [status, setStatus] = useState<AuthStatus>(() =>
    initialSession === undefined ? "checking" : initialSession ? "authenticated" : "anonymous",
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const applyResult = useCallback((result: AuthResult) => {
    setSession(result.outcome === "authenticated" ? result.session : null);
    setStatus(statusFromResult(result));
    setErrorMessage(result.outcome === "rejected" ? (result.reason ?? null) : null);
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
        setErrorMessage(error instanceof Error ? error.message : "请求失败，请稍后重试");
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
