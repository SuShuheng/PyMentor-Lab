import type { BrowserWindowConstructorOptions } from "electron";

import { isExplicitLocalHostname } from "@pymentor/contracts";

export interface TrustedContentPolicy {
  readonly url: string;
  readonly origin: string;
  isTrustedUrl(value: string): boolean;
}

const parsedTrustedUrl = (
  value: string,
  options: { readonly allowLoopbackHttp: boolean; readonly allowInternalProtocol: boolean },
): URL => {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("Trusted student URL is invalid");
  }
  const allowedProtocol =
    url.protocol === "https:" ||
    (options.allowInternalProtocol && url.protocol === "pymentor:" && url.host === "app") ||
    (options.allowLoopbackHttp &&
      url.protocol === "http:" &&
      isExplicitLocalHostname(url.hostname));
  if (!allowedProtocol || url.username !== "" || url.password !== "") {
    throw new Error("Trusted student URL is not allowed");
  }
  return url;
};

export const createTrustedContentPolicy = (options: {
  readonly configuredWebUrl?: string;
  readonly devServerUrl?: string;
  readonly localUrl?: string;
}): TrustedContentPolicy => {
  const configured = options.configuredWebUrl !== undefined;
  const development = !configured && options.devServerUrl !== undefined;
  const selected = configured
    ? options.configuredWebUrl
    : development
      ? options.devServerUrl
      : (options.localUrl ?? "pymentor://app/index.html");
  const parsed = parsedTrustedUrl(selected, {
    allowLoopbackHttp: development,
    allowInternalProtocol: !configured && !development,
  });
  const origin =
    parsed.protocol === "pymentor:" ? `${parsed.protocol}//${parsed.host}` : parsed.origin;
  return Object.freeze({
    url: parsed.toString().replace(/\/$/u, selected.endsWith("/") ? "/" : ""),
    origin,
    isTrustedUrl(value: string): boolean {
      try {
        const candidate = new URL(value);
        return parsed.protocol === "pymentor:"
          ? candidate.protocol === parsed.protocol && candidate.host === parsed.host
          : candidate.origin === origin;
      } catch {
        return false;
      }
    },
  });
};

export const createSecureWindowOptions = (
  preload: string,
  isPackaged: boolean,
): BrowserWindowConstructorOptions => ({
  width: 1_280,
  height: 800,
  minWidth: 960,
  minHeight: 640,
  show: false,
  autoHideMenuBar: true,
  backgroundColor: "#ffffff",
  webPreferences: {
    preload,
    nodeIntegration: false,
    nodeIntegrationInWorker: false,
    nodeIntegrationInSubFrames: false,
    contextIsolation: true,
    sandbox: true,
    webSecurity: true,
    allowRunningInsecureContent: false,
    experimentalFeatures: false,
    webviewTag: false,
    navigateOnDragDrop: false,
    devTools: !isPackaged,
  },
});

interface FrameLike {
  readonly url: string;
}

interface WebContentsLike {
  readonly id: number;
  readonly mainFrame: FrameLike;
  isDestroyed(): boolean;
}

interface WindowLike {
  readonly webContents: WebContentsLike;
  isDestroyed(): boolean;
}

export const authorizeIpcSender = (
  event: { readonly sender: WebContentsLike; readonly senderFrame: FrameLike | null },
  window: WindowLike | null,
  policy: TrustedContentPolicy,
): boolean => {
  if (
    window === null ||
    window.isDestroyed() ||
    window.webContents.isDestroyed() ||
    event.sender.isDestroyed() ||
    event.sender.id !== window.webContents.id ||
    event.senderFrame === null ||
    event.senderFrame !== event.sender.mainFrame
  ) {
    return false;
  }
  return policy.isTrustedUrl(event.senderFrame.url);
};

interface SessionLike {
  setPermissionRequestHandler(handler: (...args: any[]) => void): void;
  setPermissionCheckHandler(handler: (...args: any[]) => boolean): void;
  on(name: "will-download", handler: (event: { preventDefault(): void }) => void): void;
  removeListener(name: "will-download", handler: (event: { preventDefault(): void }) => void): void;
  readonly webRequest: {
    onHeadersReceived(
      handler:
        | ((
            details: { responseHeaders?: Record<string, string[] | string> },
            callback: (response: { responseHeaders: Record<string, string[] | string> }) => void,
          ) => void)
        | null,
    ): void;
  };
}

export const installSessionSecurity = (session: SessionLike, csp: () => string): (() => void) => {
  session.setPermissionRequestHandler(
    (_webContents, _permission, callback: (allowed: boolean) => void) => {
      callback(false);
    },
  );
  session.setPermissionCheckHandler(() => false);
  const denyDownload = (event: { preventDefault(): void }): void => event.preventDefault();
  session.on("will-download", denyDownload);
  session.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...(details.responseHeaders ?? {}),
        "Content-Security-Policy": [csp()],
        "X-Content-Type-Options": ["nosniff"],
        "Referrer-Policy": ["no-referrer"],
      },
    });
  });
  return () => {
    session.removeListener("will-download", denyDownload);
    session.webRequest.onHeadersReceived(null);
  };
};

interface NavigableWebContents {
  on(name: string, handler: (...args: any[]) => void): void;
  removeListener(name: string, handler: (...args: any[]) => void): void;
  setWindowOpenHandler(handler: (details: { url: string }) => { action: "deny" }): void;
}

export const installNavigationSecurity = (
  webContents: NavigableWebContents,
  policy: TrustedContentPolicy,
): (() => void) => {
  const preventUntrustedNavigation = (event: { preventDefault(): void }, url: string): void => {
    if (!policy.isTrustedUrl(url)) event.preventDefault();
  };
  const denyWebview = (event: { preventDefault(): void }): void => event.preventDefault();
  webContents.on("will-navigate", preventUntrustedNavigation);
  webContents.on("will-redirect", preventUntrustedNavigation);
  webContents.on("will-attach-webview", denyWebview);
  webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  return () => {
    webContents.removeListener("will-navigate", preventUntrustedNavigation);
    webContents.removeListener("will-redirect", preventUntrustedNavigation);
    webContents.removeListener("will-attach-webview", denyWebview);
  };
};

export const buildContentSecurityPolicy = (
  trustedOrigin: string,
  apiOrigin: string | null,
): string => {
  const connect = ["'self'", trustedOrigin];
  if (apiOrigin !== null) connect.push(apiOrigin);
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "media-src 'self' data: blob:",
    `connect-src ${connect.join(" ")}`,
    "object-src 'none'",
    "base-uri 'self'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
  ].join("; ");
};
