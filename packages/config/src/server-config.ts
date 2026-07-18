export const DEFAULT_SERVER_URL = "http://localhost:8000";
export const SERVER_URL_STORAGE_KEY = "pymentor.apiBaseUrl";

export type ServerConnectionResult = {
  message: string;
  ok: boolean;
};

export function normalizeServerUrl(value: string): string {
  const candidate = value.trim();
  if (!/^https?:\/\//i.test(candidate)) {
    throw new Error("服务器地址必须以 http:// 或 https:// 开头");
  }

  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error("服务器地址格式不正确");
  }

  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("服务器地址不能包含账号、查询参数或片段");
  }

  const path = parsed.pathname.replace(/\/+$/, "");
  return `${parsed.origin}${path === "/" ? "" : path}`;
}

export function readServerUrl(
  storage: Pick<Storage, "getItem"> = window.localStorage,
): string {
  const stored = storage.getItem(SERVER_URL_STORAGE_KEY);
  if (!stored) return DEFAULT_SERVER_URL;

  try {
    return normalizeServerUrl(stored);
  } catch {
    return DEFAULT_SERVER_URL;
  }
}

export function saveServerUrl(
  value: string,
  storage: Pick<Storage, "setItem"> = window.localStorage,
): string {
  const normalized = normalizeServerUrl(value);
  storage.setItem(SERVER_URL_STORAGE_KEY, normalized);
  return normalized;
}

export async function testServerConnection(
  value: string,
  fetcher: typeof fetch = fetch,
): Promise<ServerConnectionResult> {
  let baseUrl: string;
  try {
    baseUrl = normalizeServerUrl(value);
  } catch (error) {
    return {
      ok: false,
      message: error instanceof Error ? error.message : "服务器地址格式不正确",
    };
  }

  try {
    const response = await fetcher(`${baseUrl}/system/ping`, {
      credentials: "include",
      headers: { Accept: "application/json" },
      method: "GET",
    });

    if (!response.ok) {
      return {
        ok: false,
        message: `服务器返回 ${response.status}，请确认服务已启动`,
      };
    }

    return { ok: true, message: "服务器连接成功" };
  } catch {
    return { ok: false, message: "无法连接服务器，请检查地址与网络" };
  }
}
