import { client } from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";

/**
 * Agent prompt tuning API wrapper for FE-017 / BE-020.
 *
 * BE-020 exposes five admin endpoints under `/api/v1/admin/agent-prompts`:
 *   GET    /{node}                       — currently published prompt
 *   GET    /{node}/history               — versioned audit trail
 *   POST   /{node}                       — save a new draft version (idempotent)
 *   POST   /{node}/{version}/publish     — promote a draft to the live prompt
 *   POST   /{node}/dry-run               — stubbed; returns implemented=false + note
 *
 * The generated `@pymentor/api-client` SDK does not yet expose these routes
 * because BE-020 lives on the backend branch and the OpenAPI regeneration
 * has not picked it up. Until that happens we call the endpoints through the
 * same hey-api `client` instance the generated SDK uses, keeping auth, base
 * URL and `fetch` configuration identical to every other admin call — the
 * same pattern established by `admin-overview-api.ts` (FE-013).
 *
 * The dry-run endpoint is deliberately honest: it surfaces the backend
 * `implemented=false` note verbatim instead of faking a result, so admins
 * cannot mistake a stub for a real evaluation.
 */

export const AGENT_PROMPT_NODES = [
  "orchestrator",
  "profile",
  "path",
  "resource",
  "coach",
  "assessment",
] as const;

export type AgentPromptNode = (typeof AGENT_PROMPT_NODES)[number];

export type AgentPromptVersion = {
  node: AgentPromptNode;
  version: number;
  prompt_text: string;
  /** ISO timestamp; present on history/published rows, omitted on fresh drafts. */
  published_at?: string | null;
  /** ISO timestamp the draft was persisted; present on fresh drafts. */
  created_at?: string | null;
  updated_by: string;
  /** Whether this version is currently serving live traffic. */
  is_current?: boolean;
  /** Whether this version has been promoted to a published prompt. */
  is_published?: boolean;
};

export type AgentPromptHistory = {
  items: AgentPromptVersion[];
};

export type AgentPromptPublishResult = {
  node: AgentPromptNode;
  version: number;
  published_at: string;
  updated_by: string;
  is_published: true;
};

/**
 * BE-020 dry-run contract. `implemented` is `false` until the backend lands
 * the evaluation harness; the `note` explains why and must be rendered to
 * the admin verbatim.
 */
export type AgentPromptDryRunResult = {
  implemented: false;
  note: string;
};

export type AgentPromptQuery = {
  accessToken: string;
  node: AgentPromptNode;
};

export type AgentPromptSaveQuery = {
  accessToken: string;
  node: AgentPromptNode;
  promptText: string;
  /** Caller-supplied idempotency key; repeated saves with the same key are safe. */
  idempotencyKey: string;
};

export type AgentPromptPublishQuery = {
  accessToken: string;
  node: AgentPromptNode;
  version: number;
  idempotencyKey: string;
};

export type AgentPromptDryRunQuery = {
  accessToken: string;
  node: AgentPromptNode;
  promptText: string;
  idempotencyKey: string;
};

export function configureAdminAgentPromptClient(): void {
  client.setConfig({
    baseUrl: readServerUrl(),
    credentials: "include",
    fetch,
  });
}

function errorDetail(error: unknown): string | undefined {
  if (!error || typeof error !== "object") return undefined;
  const detail = Reflect.get(error, "detail");
  return typeof detail === "string" ? detail : undefined;
}

function promptError(error: unknown, fallback: string): Error {
  const detail = errorDetail(error);
  return new Error(detail ?? fallback);
}

export async function fetchCurrentAgentPrompt({
  accessToken,
  node,
}: AgentPromptQuery): Promise<AgentPromptVersion> {
  configureAdminAgentPromptClient();
  const { data, error, response } = await client.get<AgentPromptVersion>({
    headers: { Authorization: `Bearer ${accessToken}` },
    url: `/api/v1/admin/agent-prompts/${node}`,
  });
  if (!response.ok || !data) {
    throw promptError(error, `Agent 提示词加载失败：${node}`);
  }
  return data;
}

export async function fetchAgentPromptHistory({
  accessToken,
  node,
}: AgentPromptQuery): Promise<AgentPromptHistory> {
  configureAdminAgentPromptClient();
  const { data, error, response } = await client.get<AgentPromptHistory>({
    headers: { Authorization: `Bearer ${accessToken}` },
    url: `/api/v1/admin/agent-prompts/${node}/history`,
  });
  if (!response.ok || !data) {
    throw promptError(error, `Agent 提示词历史加载失败：${node}`);
  }
  return data;
}

export async function saveAgentPromptDraft({
  accessToken,
  node,
  promptText,
  idempotencyKey,
}: AgentPromptSaveQuery): Promise<AgentPromptVersion> {
  configureAdminAgentPromptClient();
  const { data, error, response } = await client.post<AgentPromptVersion>({
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Idempotency-Key": idempotencyKey,
    },
    body: { prompt_text: promptText },
    url: `/api/v1/admin/agent-prompts/${node}`,
  });
  if (!response.ok || !data) {
    throw promptError(error, `Agent 提示词保存失败：${node}`);
  }
  return data;
}

export async function publishAgentPromptVersion({
  accessToken,
  node,
  version,
  idempotencyKey,
}: AgentPromptPublishQuery): Promise<AgentPromptPublishResult> {
  configureAdminAgentPromptClient();
  const { data, error, response } = await client.post<AgentPromptPublishResult>({
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Idempotency-Key": idempotencyKey,
    },
    body: {},
    url: `/api/v1/admin/agent-prompts/${node}/${version}/publish`,
  });
  if (!response.ok || !data) {
    throw promptError(error, `Agent 提示词发布失败：${node} v${version}`);
  }
  return data;
}

/**
 * Calls the BE-020 dry-run stub. The backend currently responds with
 * `implemented=false` plus an explanatory note; this wrapper returns that
 * payload untouched so the UI can surface the note honestly instead of
 * fabricating an evaluation result.
 */
export async function dryRunAgentPrompt({
  accessToken,
  node,
  promptText,
  idempotencyKey,
}: AgentPromptDryRunQuery): Promise<AgentPromptDryRunResult> {
  configureAdminAgentPromptClient();
  const { data, error, response } = await client.post<AgentPromptDryRunResult>({
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Idempotency-Key": idempotencyKey,
    },
    body: { prompt_text: promptText },
    url: `/api/v1/admin/agent-prompts/${node}/dry-run`,
  });
  if (!response.ok || !data) {
    throw promptError(error, `Agent 提示词试运行失败：${node}`);
  }
  return data;
}

/**
 * Generates a stable, traceable idempotency key. The `node` (and version,
 * when present) is embedded in the key so audit entries map back to the
 * exact tuning operation without leaking prompt contents.
 */
export function agentPromptIdempotencyKey(
  node: AgentPromptNode,
  scope: "draft" | "publish" | "dry-run",
  version?: number,
): string {
  return version === undefined
    ? `agent-prompt-${node}-${scope}-${globalThis.crypto.randomUUID()}`
    : `agent-prompt-${node}-${version}-${scope}-${globalThis.crypto.randomUUID()}`;
}
