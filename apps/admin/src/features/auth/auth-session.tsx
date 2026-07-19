import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  browserAdminAuthApi,
  type AdminAuthApi,
  type AuthResult,
  type AuthSession,
} from "./auth-api";

export {
  adminSession,
  browserAdminAuthApi,
  studentSession,
  type AdminAuthApi,
  type AuthResult,
  type AuthSession,
} from "./auth-api";

type AuthContextValue = {
  errorMessage: string | null;
  login(input: { identifier: string; password: string }): Promise<void>;
  refresh(): Promise<void>;
  session: AuthSession | null;
  signOut(): void;
  status: "anonymous" | "authenticated" | "checking" | "error" | "refresh-failed";
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
  const [session, setSession] = useState<AuthSession | null>(initialSession ?? null);
  const [status, setStatus] = useState<AuthContextValue["status"]>(() =>
    initialSession === undefined ? "checking" : initialSession ? "authenticated" : "anonymous",
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
          setErrorMessage(error instanceof Error ? error.message : "管理员登录失败");
        }
      },
      refresh,
      session,
      signOut: () => {
        api.signOut();
        setSession(null);
        setStatus("anonymous");
      },
      status,
    }),
    [api, applyResult, errorMessage, refresh, session, status],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAdminAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAdminAuth must be used within AdminAuthProvider");
  return value;
}
