import { describe, expect, it, vi } from "vitest";

import {
  normalizeServerUrl,
  readServerUrl,
  saveServerUrl,
  testServerConnection,
} from "./server-config";

function memoryStorage(): Storage {
  const values = new Map<string, string>();

  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  };
}

describe("server configuration", () => {
  it("normalizes and persists only a safe HTTP base URL", () => {
    const storage = memoryStorage();

    expect(normalizeServerUrl(" https://lab.example.edu:8443/ ")).toBe(
      "https://lab.example.edu:8443",
    );
    expect(() => normalizeServerUrl("ftp://lab.example.edu")).toThrow(
      "服务器地址必须以 http:// 或 https:// 开头",
    );
    expect(() =>
      normalizeServerUrl("https://user:secret@lab.example.edu"),
    ).toThrow("服务器地址不能包含账号、查询参数或片段");

    saveServerUrl("http://192.168.1.12:8000/", storage);
    expect(readServerUrl(storage)).toBe("http://192.168.1.12:8000");
    expect(
      [...Array(storage.length)].map((_, index) => storage.key(index)),
    ).toEqual(["pymentor.apiBaseUrl"]);
  });

  it("checks the frozen /system/ping endpoint and reports unreachable servers", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(
      testServerConnection("http://localhost:8000", fetcher),
    ).resolves.toEqual({
      ok: true,
      message: "服务器连接成功",
    });
    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/system/ping",
      expect.objectContaining({ method: "GET" }),
    );
    await expect(
      testServerConnection("http://localhost:8000", fetcher),
    ).resolves.toEqual({
      ok: false,
      message: "无法连接服务器，请检查地址与网络",
    });
  });
});
