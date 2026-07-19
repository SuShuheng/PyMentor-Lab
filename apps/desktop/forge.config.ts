import { MakerSquirrel } from "@electron-forge/maker-squirrel";
import { FusesPlugin } from "@electron-forge/plugin-fuses";
import { VitePlugin } from "@electron-forge/plugin-vite";
import type { ForgeConfig } from "@electron-forge/shared-types";
import { FuseV1Options, FuseVersion, type FuseV1Config } from "@electron/fuses";

const fuseConfig: FuseV1Config = {
  version: FuseVersion.V1,
  strictlyRequireAllFuses: true,
  [FuseV1Options.RunAsNode]: false,
  [FuseV1Options.EnableCookieEncryption]: true,
  [FuseV1Options.EnableNodeOptionsEnvironmentVariable]: false,
  [FuseV1Options.EnableNodeCliInspectArguments]: false,
  [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: true,
  [FuseV1Options.OnlyLoadAppFromAsar]: true,
  [FuseV1Options.LoadBrowserProcessSpecificV8Snapshot]: false,
  [FuseV1Options.GrantFileProtocolExtraPrivileges]: false,
  [FuseV1Options.WasmTrapHandlers]: true,
};

const config: ForgeConfig = {
  packagerConfig: {
    asar: true,
    executableName: "PyMentorLab",
    appBundleId: "edu.pymentor.lab",
    appCopyright: "Copyright © 2026 PyMentor Lab",
    icon: "build/icon",
  },
  makers: [
    new MakerSquirrel({
      name: "PyMentorLab",
      authors: "PyMentor Lab",
      description: "Secure student desktop shell for PyMentor Lab",
      setupExe: "PyMentorLab-Setup.exe",
      noMsi: true,
      setupIcon: "build/icon.ico",
      iconUrl: "file://build/icon.ico",
    }),
  ],
  plugins: [
    new VitePlugin({
      build: [
        { entry: "src/main.ts", config: "vite.main.config.ts" },
        { entry: "src/preload.ts", config: "vite.preload.config.ts" },
      ],
      renderer: [{ name: "main_window", config: "vite.renderer.config.ts" }],
      concurrent: false,
    }),
    new FusesPlugin(fuseConfig),
  ],
};

export default config;
