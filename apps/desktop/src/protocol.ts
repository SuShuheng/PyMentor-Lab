import { readFile } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";

import type { Protocol } from "electron";

const mimeTypes: Readonly<Record<string, string>> = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};

const localCsp = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "object-src 'none'",
  "base-uri 'none'",
  "frame-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'none'",
].join("; ");

export const installLocalAppProtocol = (protocol: Protocol, rendererRoot: string): (() => void) => {
  const canonicalRoot = resolve(rendererRoot);
  protocol.handle("pymentor", async (request) => {
    try {
      const url = new URL(request.url);
      if (url.host !== "app" || url.search !== "" || url.hash !== "") {
        return new Response("Not found", { status: 404 });
      }
      const relative = decodeURIComponent(url.pathname).replace(/^\/+/, "") || "index.html";
      const filePath = resolve(canonicalRoot, relative);
      if (filePath !== canonicalRoot && !filePath.startsWith(`${canonicalRoot}${sep}`)) {
        return new Response("Forbidden", { status: 403 });
      }
      const content = await readFile(filePath);
      return new Response(new Uint8Array(content), {
        status: 200,
        headers: {
          "content-type": mimeTypes[extname(filePath).toLowerCase()] ?? "application/octet-stream",
          "content-security-policy": localCsp,
          "x-content-type-options": "nosniff",
          "referrer-policy": "no-referrer",
        },
      });
    } catch {
      return new Response("Not found", { status: 404 });
    }
  });
  return () => {
    void protocol.unhandle("pymentor");
  };
};
