import { randomUUID } from "node:crypto";
import { join, resolve } from "node:path";

import { app, BrowserWindow, dialog, ipcMain, Menu, protocol, shell } from "electron";
import squirrelStartup from "electron-squirrel-startup";

import { registerDesktopIpc, DesktopOperationError } from "./ipc/register.js";
import { installLocalAppProtocol } from "./protocol.js";
import {
  authorizeIpcSender,
  buildContentSecurityPolicy,
  createSecureWindowOptions,
  createTrustedContentPolicy,
  installNavigationSecurity,
  installSessionSecurity,
} from "./security.js";
import { ArtifactExportError, exportArtifact } from "./services/export-artifact.js";
import { ServerConfigStore } from "./services/server-config.js";

protocol.registerSchemesAsPrivileged([
  {
    scheme: "pymentor",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: false,
    },
  },
]);
app.enableSandbox();

let mainWindow: BrowserWindow | null = null;
let disposeWindowSecurity: (() => void) | null = null;
let disposeProtocol: (() => void) | null = null;

const rendererRoot = resolve(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}`);
const localRendererUrl = "pymentor://app/index.html";

const createStudentWindow = async (): Promise<void> => {
  const policy = createTrustedContentPolicy({
    configuredWebUrl: process.env.PYMENTOR_DESKTOP_WEB_URL,
    devServerUrl: MAIN_WINDOW_VITE_DEV_SERVER_URL,
    localUrl: localRendererUrl,
  });
  const window = new BrowserWindow(
    createSecureWindowOptions(resolve(__dirname, "preload.js"), app.isPackaged),
  );
  mainWindow = window;
  const configStore = new ServerConfigStore(
    join(app.getPath("userData"), "server-config.json"),
    randomUUID,
  );
  const initialConfig = await configStore.get(AbortSignal.timeout(2_000));
  let currentBaseUrl = initialConfig.baseUrl;
  const session = window.webContents.session;
  const disposeSession = installSessionSecurity(session, () =>
    buildContentSecurityPolicy(
      policy.origin,
      currentBaseUrl === null ? null : new URL(currentBaseUrl).origin,
    ),
  );
  const disposeNavigation = installNavigationSecurity(window.webContents, policy);
  const disposeIpc = registerDesktopIpc({
    ipcMain,
    authorize: (event) => authorizeIpcSender(event, mainWindow, policy),
    getVersion: () => app.getVersion(),
    openExternal: async (body, signal) => {
      if (signal.aborted) throw new DesktopOperationError("CANCELLED", "Open external cancelled");
      await shell.openExternal(body.url, { activate: true });
      if (signal.aborted) throw new DesktopOperationError("CANCELLED", "Open external cancelled");
      return { opened: true };
    },
    exportArtifact: (body, signal) =>
      exportArtifact(
        body,
        {
          chooseDestination: async (suggestedName) => {
            const result = await dialog.showSaveDialog(window, {
              title: "Export PyMentor artifact",
              defaultPath: join(app.getPath("downloads"), suggestedName),
              properties: ["createDirectory", "showOverwriteConfirmation"],
            });
            return result.canceled || result.filePath === ""
              ? { canceled: true }
              : { canceled: false, filePath: result.filePath };
          },
          fetchArtifact: async (artifactId, fetchSignal) => {
            if (currentBaseUrl === null) {
              throw new ArtifactExportError("CONFLICT", "Server address is not configured");
            }
            const endpoint = new URL(
              `/api/v1/resource-artifacts/${encodeURIComponent(artifactId)}/content`,
              currentBaseUrl,
            );
            return session.fetch(endpoint.toString(), {
              credentials: "include",
              redirect: "error",
              signal: fetchSignal,
            });
          },
          randomId: randomUUID,
        },
        signal,
      ),
    getServerConfig: (signal) => configStore.get(signal),
    setServerConfig: async (body, signal) => {
      const saved = await configStore.set(body, signal);
      currentBaseUrl = saved.baseUrl;
      return saved;
    },
    operationTimeoutMs: 30_000,
    rateLimitMaxRequests: 60,
    rateLimitWindowMs: 10_000,
  });
  disposeWindowSecurity = () => {
    disposeIpc();
    disposeNavigation();
    disposeSession();
  };
  window.once("ready-to-show", () => window.show());
  window.once("closed", () => {
    disposeWindowSecurity?.();
    disposeWindowSecurity = null;
    mainWindow = null;
  });
  await window.loadURL(policy.url);
};

const start = async (): Promise<void> => {
  app.setAppUserModelId("edu.pymentor.lab");
  Menu.setApplicationMenu(null);
  disposeProtocol = installLocalAppProtocol(protocol, rendererRoot);
  await createStudentWindow();
};

if (squirrelStartup) {
  app.quit();
} else if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow !== null) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
  app
    .whenReady()
    .then(start)
    .catch(() => app.quit());
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) void createStudentWindow();
  });
  app.on("window-all-closed", () => app.quit());
  app.on("will-quit", () => {
    disposeWindowSecurity?.();
    disposeProtocol?.();
  });
}
