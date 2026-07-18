/** Strict BE-010 Provider configuration contracts. */

import { z } from "zod";

const Timestamp = z.string().datetime({ offset: true });
const Uuid = z.string().uuid();
const ProviderParams = z.record(z.string(), z.unknown());
const ProviderEndpoint = z.string().url().refine((value) => {
  const parsed = new URL(value);
  const loopback = new Set(["127.0.0.1", "localhost", "[::1]"]).has(parsed.hostname);
  return (
    (parsed.protocol === "https:" || (parsed.protocol === "http:" && loopback)) &&
    parsed.username.length === 0 &&
    parsed.password.length === 0
  );
}, "Provider endpoint must use HTTPS without embedded credentials");

export const ProviderType = z.enum([
  "LLM",
  "TTS",
  "ASR",
  "IMAGE",
  "OCR",
  "MODERATION",
  "EMBEDDING",
]);
export type ProviderType = z.infer<typeof ProviderType>;

export const ProviderConfigCreate = z
  .object({
    provider_type: ProviderType,
    vendor: z.string().min(1).max(64).regex(/^[A-Za-z0-9._-]+$/),
    model: z.string().min(1).max(128).regex(/^[A-Za-z0-9._:/-]+$/),
    api_key: z.string().min(8).max(4096),
    endpoint: ProviderEndpoint.nullable(),
    params: ProviderParams,
    enabled: z.boolean(),
  })
  .strict();
export type ProviderConfigCreate = z.infer<typeof ProviderConfigCreate>;

export const ProviderConfigUpdate = z
  .object({
    vendor: z.string().min(1).max(64).regex(/^[A-Za-z0-9._-]+$/).optional(),
    model: z.string().min(1).max(128).regex(/^[A-Za-z0-9._:/-]+$/).optional(),
    api_key: z.string().min(8).max(4096).optional(),
    endpoint: ProviderEndpoint.nullable().optional(),
    params: ProviderParams.optional(),
    enabled: z.boolean().optional(),
  })
  .strict()
  .refine((value) => Object.keys(value).length > 0, "at least one field is required");
export type ProviderConfigUpdate = z.infer<typeof ProviderConfigUpdate>;

export const ProviderConfigView = z
  .object({
    id: Uuid,
    provider_type: ProviderType,
    vendor: z.string(),
    model: z.string(),
    api_key_masked: z.string(),
    endpoint: z.string().nullable(),
    params: ProviderParams,
    enabled: z.boolean(),
    version: z.number().int().positive(),
    created_at: Timestamp,
    updated_at: Timestamp,
  })
  .strict();
export type ProviderConfigView = z.infer<typeof ProviderConfigView>;

export const ProviderConfigPage = z
  .object({
    items: z.array(ProviderConfigView),
  })
  .strict();
export type ProviderConfigPage = z.infer<typeof ProviderConfigPage>;

export const ProviderConnectivityView = z
  .object({
    ok: z.boolean(),
    latency_ms: z.number().int().nonnegative(),
    status_code: z.number().int().nullable(),
    detail: z.string().min(1).max(128),
  })
  .strict();
export type ProviderConnectivityView = z.infer<typeof ProviderConnectivityView>;
