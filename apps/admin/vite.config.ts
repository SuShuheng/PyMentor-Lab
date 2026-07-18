import react from "@vitejs/plugin-react";
import { createRequire } from "node:module";
import { dirname } from "node:path";
import { defineConfig } from "vitest/config";

const require = createRequire(import.meta.url);

function packageRoot(name: string): string {
  return dirname(require.resolve(`${name}/package.json`));
}

const localReact = packageRoot("react");
const localReactDom = packageRoot("react-dom");
const localPhosphor = packageRoot("@phosphor-icons/react");

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: /^react$/, replacement: localReact },
      { find: /^react\/(.*)$/, replacement: `${localReact}/$1` },
      { find: /^react-dom$/, replacement: localReactDom },
      { find: /^react-dom\/(.*)$/, replacement: `${localReactDom}/$1` },
      { find: /^@phosphor-icons\/react$/, replacement: localPhosphor },
    ],
    dedupe: ["react", "react-dom"],
  },
  server: {
    host: "0.0.0.0",
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
