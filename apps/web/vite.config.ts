import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

function localPackagePath(path: string): string {
  const pathname = decodeURIComponent(new URL(path, import.meta.url).pathname);
  return pathname.replace(/^\/(?=[A-Za-z]:)/, "");
}

const localReact = localPackagePath("./node_modules/react");
const localReactDom = localPackagePath("./node_modules/react-dom");
const localPhosphor = localPackagePath("./node_modules/@phosphor-icons/react");

export default defineConfig({
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          icons: ["@phosphor-icons/react"],
          motion: ["framer-motion"],
          react: ["react", "react-dom", "react-router-dom"],
        },
      },
    },
  },
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
