import { client } from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";

/**
 * Aggregate overview counts served by BE-017 `GET /api/v1/admin/overview`.
 *
 * The generated API client (`@pymentor/api-client`) does not yet expose this
 * endpoint because BE-017 lives on the backend branch and has not been merged
 * to `main`, so the OpenAPI regeneration has not picked it up. Until that
 * happens we call the endpoint through the same hey-api `client` instance the
 * generated SDK uses, which keeps authentication, base URL and `fetch`
 * configuration identical to every other admin call.
 */
export type AdminOverview = {
  active_students: number;
  pending_registrations: number;
  resource_reviews: number;
  due_reviews: number;
};

export type AdminOverviewQuery = {
  accessToken: string;
};

export function configureAdminOverviewClient(): void {
  client.setConfig({
    baseUrl: readServerUrl(),
    credentials: "include",
    fetch,
  });
}

export async function fetchAdminOverview({
  accessToken,
}: AdminOverviewQuery): Promise<AdminOverview> {
  configureAdminOverviewClient();
  const { data, error, response } = await client.get<AdminOverview>({
    headers: { Authorization: `Bearer ${accessToken}` },
    url: "/api/v1/admin/overview",
  });
  if (!response.ok || !data) {
    const detail =
      error && typeof error === "object" ? Reflect.get(error, "detail") : undefined;
    throw new Error(
      typeof detail === "string" ? detail : "管理概览数据暂时不可用，请稍后重试",
    );
  }
  return data;
}
