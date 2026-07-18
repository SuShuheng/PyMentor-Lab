import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const localReact = fileURLToPath(
  new URL("./node_modules/react", import.meta.url),
);
const localReactDom = fileURLToPath(
  new URL("./node_modules/react-dom", import.meta.url),
);
const localPhosphor = fileURLToPath(
  new URL("./node_modules/@phosphor-icons/react", import.meta.url),
);

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
