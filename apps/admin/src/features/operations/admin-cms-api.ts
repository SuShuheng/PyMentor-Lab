import { client } from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";

/**
 * Minimal CMS typed wrapper for FE-024 consuming BE-027 (`/api/v1/admin/cms`).
 *
 * Mirrors the FE-013 pattern from `admin-overview-api.ts`: the generated
 * hey-api `client` does not yet expose these endpoints (BE-027 lives on the
 * backend branch and the OpenAPI regeneration has not landed on `main`), so we
 * drive the same `client` instance the generated SDK uses. This keeps base URL,
 * `credentials: include`, `fetch` shim, and the `Authorization` header
 * identical to every other admin call.
 *
 * The shapes here are the V1.1 contract surfaces the UI needs. They are kept
 * narrow on purpose: BE-027 owns the authoritative Pydantic models and the
 * server performs the only validation that matters (the UI just shows whatever
 * 422 detail it returns).
 */

export type CmsNodeAudit = {
  last_actor?: string | null;
  last_event?: string | null;
  trace_id?: string | null;
};

export type CmsNode = {
  node_id: string;
  title: string;
  chapter_id: string;
  course_id?: string | null;
  learning_objectives: string[];
  prerequisites: string[];
  misconceptions: string[];
  examples: string[];
  diagnostic_items: string[];
  practice_templates: string[];
  mastery_policy_id?: string | null;
  source_ids: string[];
  content_version: string;
  published?: boolean;
  updated_at?: string | null;
  audit?: CmsNodeAudit | null;
};

export type CmsNodePage = {
  items: CmsNode[];
  page: { number: number; size: number; total_items: number; total_pages: number };
};

export type CmsNodeUpdate = {
  title: string;
  chapter_id: string;
  learning_objectives: string[];
  prerequisites: string[];
  misconceptions: string[];
  examples: string[];
  diagnostic_items: string[];
  practice_templates: string[];
  source_ids: string[];
};

export type CmsQuestionTemplateAudit = {
  last_actor?: string | null;
  last_event?: string | null;
  trace_id?: string | null;
};

export type CmsQuestionTemplate = {
  question_id: string;
  node_id: string;
  kind: string;
  prompt_template: string;
  parameter_schema: Record<string, unknown>;
  answer_schema: Record<string, unknown>;
  test_case_ids: string[];
  source_ids: string[];
  content_version: string;
  published?: boolean;
  updated_at?: string | null;
  audit?: CmsQuestionTemplateAudit | null;
};

export type CmsQuestionTemplateUpdate = {
  kind: string;
  prompt_template: string;
  parameter_schema: Record<string, unknown>;
  answer_schema: Record<string, unknown>;
  test_case_ids: string[];
  source_ids: string[];
};

export type CmsPublishResult = {
  content_version: string;
  published: boolean;
};

export type CmsQuery = { accessToken: string };

export function configureAdminCmsClient(): void {
  client.setConfig({
    baseUrl: readServerUrl(),
    credentials: "include",
    fetch,
  });
}

type ClientResult<T> = {
  data: T | undefined;
  error: unknown;
  response: Response;
};

function extractError(error: unknown, fallback: string): string {
  if (error && typeof error === "object") {
    const detail = Reflect.get(error, "detail");
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((entry) =>
          entry && typeof entry === "object" && typeof Reflect.get(entry, "msg") === "string"
            ? String(Reflect.get(entry, "msg"))
            : null,
        )
        .filter((message): message is string => message !== null);
      if (messages.length > 0) return messages.join("；");
    }
    const message = Reflect.get(error, "message");
    if (typeof message === "string" && message.trim()) return message;
  }
  return fallback;
}

function unwrap<T>(result: ClientResult<T>, fallback: string): T {
  if (!result.response.ok || result.data === undefined) {
    throw new Error(extractError(result.error, fallback));
  }
  return result.data;
}

const authHeaders = (accessToken: string) => ({
  Authorization: `Bearer ${accessToken}`,
});

export async function listCmsNodes({
  accessToken,
  query,
}: CmsQuery & {
  query?: { q?: string; page?: number; page_size?: number };
}): Promise<CmsNodePage> {
  configureAdminCmsClient();
  const search = new URLSearchParams();
  if (query?.q) search.set("q", query.q);
  if (query?.page) search.set("page", String(query.page));
  if (query?.page_size) search.set("page_size", String(query.page_size));
  const qs = search.toString() ? `?${search.toString()}` : "";
  return unwrap<CmsNodePage>(
    await client.get<CmsNodePage>({
      headers: authHeaders(accessToken),
      url: `/api/v1/admin/cms/nodes${qs}`,
    }),
    "知识节点列表暂时不可用，请稍后重试",
  );
}

export async function fetchCmsNode({ accessToken, nodeId }: CmsQuery & { nodeId: string }): Promise<CmsNode> {
  configureAdminCmsClient();
  return unwrap<CmsNode>(
    await client.get<CmsNode>({
      headers: authHeaders(accessToken),
      url: `/api/v1/admin/cms/nodes/${encodeURIComponent(nodeId)}`,
    }),
    "知识节点详情暂时不可用，请稍后重试",
  );
}

export async function updateCmsNode({
  accessToken,
  nodeId,
  body,
  idempotencyKey,
}: CmsQuery & { nodeId: string; body: CmsNodeUpdate; idempotencyKey: string }): Promise<CmsNode> {
  configureAdminCmsClient();
  return unwrap<CmsNode>(
    await client.put<CmsNode>({
      body,
      headers: {
        ...authHeaders(accessToken),
        "Idempotency-Key": idempotencyKey,
      },
      url: `/api/v1/admin/cms/nodes/${encodeURIComponent(nodeId)}`,
    }),
    "节点保存失败，请稍后重试",
  );
}

export async function publishCmsNode({
  accessToken,
  nodeId,
  idempotencyKey,
}: CmsQuery & { nodeId: string; idempotencyKey: string }): Promise<CmsPublishResult> {
  configureAdminCmsClient();
  return unwrap<CmsPublishResult>(
    await client.post<CmsPublishResult>({
      body: {},
      headers: {
        ...authHeaders(accessToken),
        "Idempotency-Key": idempotencyKey,
      },
      url: `/api/v1/admin/cms/nodes/${encodeURIComponent(nodeId)}/publish`,
    }),
    "节点发布失败，请稍后重试",
  );
}

export async function fetchCmsQuestionTemplate({
  accessToken,
  templateId,
}: CmsQuery & { templateId: string }): Promise<CmsQuestionTemplate> {
  configureAdminCmsClient();
  return unwrap<CmsQuestionTemplate>(
    await client.get<CmsQuestionTemplate>({
      headers: authHeaders(accessToken),
      url: `/api/v1/admin/cms/question_templates/${encodeURIComponent(templateId)}`,
    }),
    "题目模板详情暂时不可用，请稍后重试",
  );
}

export async function updateCmsQuestionTemplate({
  accessToken,
  templateId,
  body,
  idempotencyKey,
}: CmsQuery & {
  templateId: string;
  body: CmsQuestionTemplateUpdate;
  idempotencyKey: string;
}): Promise<CmsQuestionTemplate> {
  configureAdminCmsClient();
  return unwrap<CmsQuestionTemplate>(
    await client.put<CmsQuestionTemplate>({
      body,
      headers: {
        ...authHeaders(accessToken),
        "Idempotency-Key": idempotencyKey,
      },
      url: `/api/v1/admin/cms/question_templates/${encodeURIComponent(templateId)}`,
    }),
    "题目模板保存失败，请稍后重试",
  );
}

export async function publishCmsQuestionTemplate({
  accessToken,
  templateId,
  idempotencyKey,
}: CmsQuery & { templateId: string; idempotencyKey: string }): Promise<CmsPublishResult> {
  configureAdminCmsClient();
  return unwrap<CmsPublishResult>(
    await client.post<CmsPublishResult>({
      body: {},
      headers: {
        ...authHeaders(accessToken),
        "Idempotency-Key": idempotencyKey,
      },
      url: `/api/v1/admin/cms/question_templates/${encodeURIComponent(templateId)}/publish`,
    }),
    "题目模板发布失败，请稍后重试",
  );
}

export function cmsCommandKey(prefix: string): string {
  return `${prefix}-${globalThis.crypto.randomUUID()}`;
}
