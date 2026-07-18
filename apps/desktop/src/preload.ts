import { contextBridge, ipcRenderer } from "electron";

import { createDesktopBridge } from "./preload-api.js";

contextBridge.exposeInMainWorld(
  "desktop",
  createDesktopBridge((channel, body) => ipcRenderer.invoke(channel, body)),
);
