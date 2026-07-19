import {
  client,
  createProviderApiV1AdminProvidersPost,
  listProvidersApiV1AdminProvidersGet,
  updateProviderApiV1AdminProvidersProviderIdPatch,
  type ProviderConfigCreateWritable,
  type ProviderConfigUpdateWritable,
  type ProviderConfigView,
  type ProviderType,
} from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";

/**
 * BE-019 typed wrapper for the System Admin Provider CRUD surface.
 *
 * The generated SDK (`@pymentor/api-client`) only exposes `list`, `create`,
 * `update` and the legacy `test` (no request body) commands because BE-019
 * lives on the backend branch and has not been merged through OpenAPI
 * regeneration yet. The missing surface — `GET /{id}` detail, `DELETE /{id}`
 * soft-delete, `POST /{id}/enable`, `POST /{id}/disable`, and the
 * candidate-key body + standardized `{ok, latency_ms, status_code, detail,
 * model_id, error_code}` response on `POST /{id}/test` — is reached through
 * the same hey-api `client` instance the generated SDK uses, so
 * authentication, base URL and `fetch` configuration stay identical to every
 * other admin call. This mirrors the FE-013 `admin-overview-api.ts` pattern.
 *
 * Security invariants enforced here:
 * - The API key is WRITE-ONLY. It only ever leaves the browser inside a
 *   `POST`/`PATCH` body or an optional `test` candidate body. No function in
 *   this module returns a decrypted/plaintext key — the backend only ever
 *   emits `api_key_masked`.
 * - Every write carries an `Idempotency-Key` header (caller-supplied) so
 *   retries and double-clicks are safe and auditable.
 */

const BASE = "/api/v1/admin/providers";

export type { ProviderConfigView, ProviderType } from "@pymentor/api-client";

export type ProviderKind = ProviderType;

/** Standardized connectivity-test result (BE-019). */
export type ProviderConnectivityResult = {
  ok: boolean;
  latency_ms: number;
  status_code: number | null;
  detail: string;
  model_id: string | null;
  error_code: string | null;
};

export type ProviderWriteHeaders = {
  accessToken: string;
  /** Caller-generated idempotency key (e.g. `provider-create-<uuid>`). */
  idempotencyKey: string;
};

export type ProviderListQuery = {
  accessToken: string;
};

export type ProviderDetailQuery = {
  accessToken: string;
  providerId: string;
};

export type ProviderCreateInput = {
  provider_type: ProviderType;
  vendor: string;
  model: string;
  api_key: string;
  endpoint: string | null;
  params: Record<string, unknown>;
  enabled: boolean;
};

export type ProviderUpdateInput = {
  vendor?: string;
  model?: string;
  api_key?: string;
  endpoint?: string | null;
  params?: Record<string, unknown>;
  enabled?: boolean;
};

export type ProviderTestOptions = {
  accessToken: string;
  providerId: string;
  /**
   * Optional candidate key for pre-save rotation validation. When supplied it
   * is sent in the body and used INSTEAD of the stored key for a one-shot
   * probe; the backend never persists it and never echoes it.
   */
  candidateApiKey?: string;
};

export function configureAdminProviderClient(): void {
  client.setConfig({
    baseUrl: readServerUrl(),
    credentials: "include",
    fetch,
  });
}

function authHeader(accessToken: string): { Authorization: string } {
  return { Authorization: `Bearer ${accessToken}` };
}

function writeHeaders({ accessToken, idempotencyKey }: ProviderWriteHeaders) {
  return {
    ...authHeader(accessToken),
    "Idempotency-Key": idempotencyKey,
  };
}

/**
 * Extract a human-readable detail message from a hey-api error envelope.
 * Falls back to a generic Chinese admin message consistent with the rest of
 * the operations layer.
 */
export function providerApiError(error: unknown, fallback: string): string {
  if (error && typeof error === "object") {
    const detail = Reflect.get(error, "detail");
    if (typeof detail === "string" && detail.length > 0) return detail;
    const message = Reflect.get(error, "message");
    if (typeof message === "string" && message.length > 0) return message;
  }
  return fallback;
}

/** BE-019 `GET /api/v1/admin/providers` — list (masked). */
export async function fetchProviders({
  accessToken,
}: ProviderListQuery): Promise<ProviderConfigView[]> {
  configureAdminProviderClient();
  const result = await listProvidersApiV1AdminProvidersGet({
    headers: authHeader(accessToken),
  });
  if (!result.data) {
    throw new Error(providerApiError(result.error, "Provider 配置加载失败，请稍后重试"));
  }
  return result.data.items;
}

/** BE-019 `GET /api/v1/admin/providers/{id}` — detail (masked). */
export async function fetchProviderDetail({
  accessToken,
  providerId,
}: ProviderDetailQuery): Promise<ProviderConfigView> {
  configureAdminProviderClient();
  const { data, error, response } = await client.get<ProviderConfigView>({
    headers: authHeader(accessToken),
    url: `${BASE}/${encodeURIComponent(providerId)}`,
  });
  if (!response.ok || !data) {
    throw new Error(providerApiError(error, "Provider 详情暂时不可用，请稍后重试"));
  }
  return data;
}

/** BE-019 `POST /api/v1/admin/providers` — create. */
export async function createProvider(
  input: ProviderCreateInput,
  headers: ProviderWriteHeaders,
): Promise<ProviderConfigView> {
  configureAdminProviderClient();
  const body: ProviderConfigCreateWritable = {
    provider_type: input.provider_type,
    vendor: input.vendor,
    model: input.model,
    api_key: input.api_key,
    endpoint: input.endpoint,
    params: input.params,
    enabled: input.enabled,
  };
  const result = await createProviderApiV1AdminProvidersPost({
    body,
    headers: writeHeaders(headers),
  });
  if (!result.data) {
    throw new Error(providerApiError(result.error, "Provider 创建失败，请稍后重试"));
  }
  return result.data;
}

/** BE-019 `PATCH /api/v1/admin/providers/{id}` — partial update. */
export async function updateProvider(
  providerId: string,
  input: ProviderUpdateInput,
  headers: ProviderWriteHeaders,
): Promise<ProviderConfigView> {
  configureAdminProviderClient();
  const body: ProviderConfigUpdateWritable = input;
  const result = await updateProviderApiV1AdminProvidersProviderIdPatch({
    body,
    headers: writeHeaders(headers),
    path: { provider_id: providerId },
  });
  if (!result.data) {
    throw new Error(providerApiError(result.error, "Provider 更新失败，请稍后重试"));
  }
  return result.data;
}

/** BE-019 `DELETE /api/v1/admin/providers/{id}` — soft delete. */
export async function deleteProvider(
  providerId: string,
  headers: ProviderWriteHeaders,
): Promise<ProviderConfigView> {
  configureAdminProviderClient();
  const { data, error, response } = await client.delete<ProviderConfigView>({
    headers: writeHeaders(headers),
    url: `${BASE}/${encodeURIComponent(providerId)}`,
  });
  if (!response.ok || !data) {
    throw new Error(providerApiError(error, "Provider 删除失败，请稍后重试"));
  }
  return data;
}

/** BE-019 `POST /api/v1/admin/providers/{id}/enable`. */
export async function enableProvider(
  providerId: string,
  headers: ProviderWriteHeaders,
): Promise<ProviderConfigView> {
  configureAdminProviderClient();
  const { data, error, response } = await client.post<ProviderConfigView>({
    body: {},
    headers: writeHeaders(headers),
    url: `${BASE}/${encodeURIComponent(providerId)}/enable`,
  });
  if (!response.ok || !data) {
    throw new Error(providerApiError(error, "Provider 启用失败，请稍后重试"));
  }
  return data;
}

/** BE-019 `POST /api/v1/admin/providers/{id}/disable`. */
export async function disableProvider(
  providerId: string,
  headers: ProviderWriteHeaders,
): Promise<ProviderConfigView> {
  configureAdminProviderClient();
  const { data, error, response } = await client.post<ProviderConfigView>({
    body: {},
    headers: writeHeaders(headers),
    url: `${BASE}/${encodeURIComponent(providerId)}/disable`,
  });
  if (!response.ok || !data) {
    throw new Error(providerApiError(error, "Provider 停用失败，请稍后重试"));
  }
  return data;
}

/**
 * BE-019 `POST /api/v1/admin/providers/{id}/test`.
 *
 * Sends an optional candidate `{ api_key }` body for pre-save rotation
 * validation; the key is never persisted or echoed. The standardized result
 * shape `{ok, latency_ms, status_code, detail, model_id, error_code}` is
 * returned regardless of success/failure (a 4xx/5xx from the probe itself is
 * still surfaced through the standardized `error_code`).
 */
export async function testProviderConnectivity({
  accessToken,
  providerId,
  candidateApiKey,
}: ProviderTestOptions): Promise<ProviderConnectivityResult> {
  configureAdminProviderClient();
  const body = candidateApiKey ? { api_key: candidateApiKey } : undefined;
  const { data, error, response } = await client.post<ProviderConnectivityResult>({
    body,
    headers: authHeader(accessToken),
    url: `${BASE}/${encodeURIComponent(providerId)}/test`,
  });
  // The endpoint returns the standardized result even on probe failure (ok=false).
  // Only network/transport problems or non-standard errors throw here.
  if (!response.ok || !data) {
    throw new Error(providerApiError(error, "Provider 连通性测试失败，请稍后重试"));
  }
  return data;
}
