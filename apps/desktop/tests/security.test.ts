import { describe, expect, it, vi } from "vitest";

import {
  authorizeIpcSender,
  createSecureWindowOptions,
  createTrustedContentPolicy,
  installSessionSecurity,
} from "../src/security.js";

describe("Electron security boundary", () => {
  it("pins hardened BrowserWindow flags and hides production devtools", () => {
    const options = createSecureWindowOptions("C:\\app\\preload.js", true);
    expect(options.webPreferences).toMatchObject({
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      experimentalFeatures: false,
      devTools: false,
      preload: "C:\\app\\preload.js",
    });
  });

  it("accepts only HTTPS or loopback dev student content", () => {
    expect(
      createTrustedContentPolicy({ configuredWebUrl: "https://learn.example.edu/app" }).url,
    ).toBe("https://learn.example.edu/app");
    expect(createTrustedContentPolicy({ devServerUrl: "http://127.0.0.1:5173" }).origin).toBe(
      "http://127.0.0.1:5173",
    );
    expect(() => createTrustedContentPolicy({ configuredWebUrl: "http://example.edu" })).toThrow();
    expect(() =>
      createTrustedContentPolicy({ configuredWebUrl: "pymentor://app/index.html" }),
    ).toThrow();
    const local = createTrustedContentPolicy({ localUrl: "pymentor://app/index.html" });
    expect(local.origin).toBe("pymentor://app");
    expect(local.isTrustedUrl("pymentor://app/lesson.html")).toBe(true);
    expect(local.isTrustedUrl("pymentor://evil/index.html")).toBe(false);
  });

  it("rejects subframes, wrong webContents, devtools and destroyed windows", () => {
    const mainFrame = { url: "https://learn.example.edu/app" };
    const trustedContents = { id: 7, isDestroyed: () => false, mainFrame };
    const trustedWindow = { isDestroyed: () => false, webContents: trustedContents };
    const policy = createTrustedContentPolicy({
      configuredWebUrl: "https://learn.example.edu/app",
    });

    expect(
      authorizeIpcSender(
        { sender: trustedContents, senderFrame: mainFrame },
        trustedWindow,
        policy,
      ),
    ).toBe(true);
    expect(
      authorizeIpcSender(
        { sender: trustedContents, senderFrame: { url: mainFrame.url } },
        trustedWindow,
        policy,
      ),
    ).toBe(false);
    expect(
      authorizeIpcSender(
        { sender: { ...trustedContents, id: 8 }, senderFrame: mainFrame },
        trustedWindow,
        policy,
      ),
    ).toBe(false);
    expect(
      authorizeIpcSender(
        { sender: trustedContents, senderFrame: { url: "devtools://devtools/bundled/" } },
        trustedWindow,
        policy,
      ),
    ).toBe(false);
    expect(
      authorizeIpcSender(
        { sender: trustedContents, senderFrame: mainFrame },
        { ...trustedWindow, isDestroyed: () => true },
        policy,
      ),
    ).toBe(false);
  });

  it("denies permissions/downloads and installs a restrictive CSP with cleanup", () => {
    let permissionRequest: ((...args: unknown[]) => void) | undefined;
    let permissionCheck: ((...args: unknown[]) => boolean) | undefined;
    let downloadHandler: ((event: { preventDefault(): void }) => void) | undefined;
    let headerHandler:
      ((details: unknown, callback: (response: unknown) => void) => void) | undefined;
    const session = {
      setPermissionRequestHandler: vi.fn((handler) => {
        permissionRequest = handler;
      }),
      setPermissionCheckHandler: vi.fn((handler) => {
        permissionCheck = handler;
      }),
      on: vi.fn((name, handler) => {
        expect(name).toBe("will-download");
        downloadHandler = handler;
      }),
      removeListener: vi.fn(),
      webRequest: {
        onHeadersReceived: vi.fn((handler) => {
          headerHandler = handler;
        }),
      },
    };

    const dispose = installSessionSecurity(session, () => "default-src 'self'; object-src 'none'");
    const permissionCallback = vi.fn();
    permissionRequest?.({}, "camera", permissionCallback);
    expect(permissionCallback).toHaveBeenCalledWith(false);
    expect(permissionCheck?.()).toBe(false);
    const downloadEvent = { preventDefault: vi.fn() };
    downloadHandler?.(downloadEvent);
    expect(downloadEvent.preventDefault).toHaveBeenCalledOnce();
    const headersCallback = vi.fn();
    headerHandler?.({ responseHeaders: { Existing: ["yes"] } }, headersCallback);
    expect(headersCallback).toHaveBeenCalledWith(
      expect.objectContaining({
        responseHeaders: expect.objectContaining({
          "Content-Security-Policy": ["default-src 'self'; object-src 'none'"],
        }),
      }),
    );
    dispose();
    expect(session.removeListener).toHaveBeenCalledWith("will-download", downloadHandler);
    expect(session.webRequest.onHeadersReceived).toHaveBeenLastCalledWith(null);
  });
});
