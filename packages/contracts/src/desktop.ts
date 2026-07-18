/** Shared runtime contracts for the narrow Electron main/preload boundary. */

import { z } from "zod";

import { ErrorEnvelope } from "./errors.js";

export const desktopIpcChannels = Object.freeze({
  getVersion: "desktop:version",
  openExternal: "desktop:open-external",
  exportArtifact: "desktop:export-artifact",
  getServerConfig: "desktop:get-server-config",
  setServerConfig: "desktop:set-server-config",
});

const privateIpv4 = (hostname: string): boolean => {
  const octets = hostname.split(".").map(Number);
  if (
    octets.length !== 4 ||
    octets.some((part) => !Number.isInteger(part) || part < 0 || part > 255)
  ) {
    return false;
  }
  const [first, second] = octets as [number, number, number, number];
  return (
    first === 10 ||
    first === 127 ||
    (first === 169 && second === 254) ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168)
  );
};

const privateIpv6 = (hostname: string): boolean => {
  if (hostname === "::1") return true;
  if (!hostname.includes(":")) return false;
  const firstHextet = hostname.split(":", 1)[0];
  if (firstHextet === undefined || !/^[0-9a-f]{1,4}$/iu.test(firstHextet)) return false;
  const first = Number.parseInt(firstHextet, 16);
  return (first >= 0xfc00 && first <= 0xfdff) || (first >= 0xfe80 && first <= 0xfebf);
};

export const isExplicitLocalHostname = (hostname: string): boolean => {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return (
    normalized === "localhost" ||
    normalized.endsWith(".localhost") ||
    normalized.endsWith(".local") ||
    privateIpv6(normalized) ||
    privateIpv4(normalized)
  );
};

const parseUrl = (value: string): URL | null => {
  try {
    return new URL(value);
  } catch {
    return null;
  }
};

export const isAllowedExternalUrl = (value: string): boolean => {
  const url = parseUrl(value);
  return (
    url !== null &&
    url.protocol === "https:" &&
    url.hostname.length > 0 &&
    url.username === "" &&
    url.password === ""
  );
};

export const isAllowedServerBaseUrl = (value: string): boolean => {
  const url = parseUrl(value);
  if (
    url === null ||
    url.hostname.length === 0 ||
    url.username !== "" ||
    url.password !== "" ||
    url.pathname !== "/" ||
    url.search !== "" ||
    url.hash !== ""
  ) {
    return false;
  }
  return (
    url.protocol === "https:" || (url.protocol === "http:" && isExplicitLocalHostname(url.hostname))
  );
};

const allowedArtifactExtension = /\.(?:txt|md|json|html|pdf|png|jpe?g|mp3|wav|vtt|zip|ipynb|py)$/iu;
const windowsReservedName = /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/iu;

export const isSafeArtifactName = (value: string): boolean =>
  value.length > 0 &&
  value.length <= 120 &&
  value === value.trim() &&
  value !== "." &&
  value !== ".." &&
  !/[\u0000-\u001f\u007f/\\:*?"<>|]/u.test(value) &&
  !value.endsWith(".") &&
  !windowsReservedName.test(value) &&
  allowedArtifactExtension.test(value);

export const DesktopVersionRequestSchema = z.undefined();
export const DesktopVersionResponseSchema = z
  .object({ version: z.string().min(1).max(64) })
  .strict();
export type DesktopVersionResponse = z.infer<typeof DesktopVersionResponseSchema>;

export const DesktopOpenExternalRequestSchema = z
  .object({ url: z.string().min(1).max(2_048).refine(isAllowedExternalUrl, "URL is not allowed") })
  .strict();
export const DesktopOpenExternalResponseSchema = z.object({ opened: z.boolean() }).strict();
export type DesktopOpenExternalRequest = z.infer<typeof DesktopOpenExternalRequestSchema>;
export type DesktopOpenExternalResponse = z.infer<typeof DesktopOpenExternalResponseSchema>;

export const DesktopExportArtifactRequestSchema = z
  .object({
    artifactId: z.string().uuid(),
    suggestedName: z.string().refine(isSafeArtifactName, "Artifact name is not allowed"),
  })
  .strict();
export const DesktopExportArtifactResponseSchema = z
  .object({
    status: z.enum(["EXPORTED", "CANCELLED"]),
    displayName: z.string().refine(isSafeArtifactName, "Artifact display name is not allowed"),
  })
  .strict();
export type DesktopExportArtifactRequest = z.infer<typeof DesktopExportArtifactRequestSchema>;
export type DesktopExportArtifactResponse = z.infer<typeof DesktopExportArtifactResponseSchema>;

export const DesktopGetServerConfigRequestSchema = z.undefined();
export const DesktopServerConfigRequestSchema = z
  .object({
    baseUrl: z
      .string()
      .min(1)
      .max(2_048)
      .refine(isAllowedServerBaseUrl, "Server URL is not allowed"),
  })
  .strict();
export const DesktopServerConfigResponseSchema = z
  .object({ baseUrl: z.string().refine(isAllowedServerBaseUrl).nullable() })
  .strict();
export type DesktopServerConfigRequest = z.infer<typeof DesktopServerConfigRequestSchema>;
export type DesktopServerConfigResponse = z.infer<typeof DesktopServerConfigResponseSchema>;

export const desktopIpcResultSchema = <T extends z.ZodTypeAny>(valueSchema: T) =>
  z.discriminatedUnion("ok", [
    z.object({ ok: z.literal(true), value: valueSchema }).strict(),
    z.object({ ok: z.literal(false), error: ErrorEnvelope }).strict(),
  ]);

export type DesktopIpcResult<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly error: z.infer<typeof ErrorEnvelope> };
