import { randomUUID } from "node:crypto";

import type { ChatCompletionChunk, StreamEvent, ToolCallDelta } from "@pymentor/contracts";

export type ProviderErrorCode =
  | "RATE_LIMITED"
  | "PROVIDER_UNAVAILABLE"
  | "CONTENT_REJECTED"
  | "TIMEOUT"
  | "CANCELLED";

export interface ProviderConfigInput {
  readonly baseUrl: string;
  readonly apiKey: string;
  readonly model: string;
  readonly timeoutMs?: number;
}

export interface ProviderConfig {
  readonly baseUrl: string;
  readonly apiKey: string;
  readonly model: string;
  readonly timeoutMs: number;
}

export interface ChatMessage {
  readonly role: "system" | "user" | "assistant" | "tool";
  readonly content: string;
  readonly name?: string;
  readonly tool_call_id?: string;
}

export interface ChatStreamRequest {
  readonly messages: readonly ChatMessage[];
  readonly temperature?: number;
  readonly maxTokens?: number;
  readonly signal?: AbortSignal;
}

export interface OpenAICompatibleChatProvider {
  stream(request: ChatStreamRequest): AsyncIterable<StreamEvent>;
}

type FetchLike = (input: string | URL, init?: RequestInit) => Promise<Response>;

export interface ProviderDependencies {
  readonly fetch?: FetchLike;
  readonly now?: () => string;
}

export class ProviderRequestError extends Error {
  constructor(
    readonly code: ProviderErrorCode,
    message: string,
    readonly retryable: boolean,
    readonly retryAfterMs?: number,
  ) {
    super(message);
    this.name = "ProviderRequestError";
  }
}

function providerUrl(value: string): URL {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("Provider base URL must be an absolute HTTPS URL.");
  }
  const loopback = new Set(["127.0.0.1", "localhost", "::1"]).has(parsed.hostname);
  if ((parsed.protocol !== "https:" && !(parsed.protocol === "http:" && loopback)) || !parsed.host) {
    throw new Error("Provider base URL must use HTTPS (loopback HTTP is allowed for development).");
  }
  if (parsed.username.length > 0 || parsed.password.length > 0) {
    throw new Error("Provider base URL must not contain embedded credentials.");
  }
  parsed.hash = "";
  parsed.search = "";
  if (!parsed.pathname.endsWith("/")) parsed.pathname += "/";
  return parsed;
}

export function parseProviderConfig(input: ProviderConfigInput): ProviderConfig {
  const baseUrl = providerUrl(input.baseUrl).toString();
  if (input.apiKey.trim().length === 0) throw new Error("Provider API key must not be empty.");
  if (input.model.trim().length === 0) throw new Error("Provider model must not be empty.");
  const timeoutMs = input.timeoutMs ?? 30_000;
  if (!Number.isInteger(timeoutMs) || timeoutMs < 50 || timeoutMs > 120_000) {
    throw new Error("Provider timeout must be an integer between 50 and 120000 milliseconds.");
  }

  const config = {
    baseUrl,
    model: input.model,
    timeoutMs,
  } as ProviderConfig;
  Object.defineProperty(config, "apiKey", {
    value: input.apiKey,
    enumerable: false,
    configurable: false,
    writable: false,
  });
  return Object.freeze(config);
}

function retryAfterMs(response: Response): number | undefined {
  const value = response.headers.get("retry-after");
  if (value === null) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.round(seconds * 1_000);
  const date = Date.parse(value);
  if (Number.isNaN(date)) return undefined;
  return Math.max(0, date - Date.now());
}

function responseError(response: Response): ProviderRequestError {
  if (response.status === 429) {
    return new ProviderRequestError(
      "RATE_LIMITED",
      "The Provider rate limit was reached.",
      true,
      retryAfterMs(response),
    );
  }
  if (response.status === 400 || response.status === 422) {
    return new ProviderRequestError(
      "CONTENT_REJECTED",
      "The Provider rejected the request content.",
      false,
    );
  }
  return new ProviderRequestError(
    "PROVIDER_UNAVAILABLE",
    `The Provider returned HTTP ${response.status}.`,
    response.status >= 500,
  );
}

async function* sseData(response: Response): AsyncGenerator<string> {
  if (response.body === null) {
    throw new ProviderRequestError(
      "PROVIDER_UNAVAILABLE",
      "The Provider returned an empty stream.",
      true,
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const normalized = buffer.replaceAll("\r\n", "\n");
      const events = normalized.split("\n\n");
      buffer = events.pop() ?? "";
      for (const event of events) {
        const data = event
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (data.length > 0) yield data;
      }
      if (done) break;
    }
    if (buffer.trim().length > 0) {
      const data = buffer
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (data.length > 0) yield data;
    }
  } finally {
    reader.releaseLock();
  }
}

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord | undefined {
  return typeof value === "object" && value !== null ? (value as UnknownRecord) : undefined;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function toolCalls(value: unknown): ToolCallDelta[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const result: ToolCallDelta[] = [];
  for (const item of value) {
    const call = record(item);
    const fn = record(call?.["function"]);
    const index = call?.["index"];
    if (typeof index !== "number" || !Number.isInteger(index) || index < 0) continue;
    result.push({
      index,
      ...(stringValue(call?.["id"]) === undefined ? {} : { id: stringValue(call?.["id"]) }),
      ...(stringValue(fn?.["name"]) === undefined ? {} : { name: stringValue(fn?.["name"]) }),
      ...(stringValue(fn?.["arguments"]) === undefined
        ? {}
        : { arguments: stringValue(fn?.["arguments"]) }),
    });
  }
  return result.length === 0 ? undefined : result;
}

function parseChunk(data: string): {
  readonly id?: string;
  readonly model?: string;
  readonly content?: string;
  readonly reasoning?: string;
  readonly tools?: ToolCallDelta[];
} {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    throw new ProviderRequestError(
      "PROVIDER_UNAVAILABLE",
      "The Provider returned an invalid streaming chunk.",
      true,
    );
  }
  const root = record(parsed);
  const choices = root?.["choices"];
  const choice = Array.isArray(choices) ? record(choices[0]) : undefined;
  const delta = record(choice?.["delta"]);
  return {
    ...(stringValue(root?.["id"]) === undefined ? {} : { id: stringValue(root?.["id"]) }),
    ...(stringValue(root?.["model"]) === undefined ? {} : { model: stringValue(root?.["model"]) }),
    ...(stringValue(delta?.["content"]) === undefined
      ? {}
      : { content: stringValue(delta?.["content"]) }),
    ...(stringValue(delta?.["reasoning_content"]) === undefined
      ? {}
      : { reasoning: stringValue(delta?.["reasoning_content"]) }),
    ...(toolCalls(delta?.["tool_calls"]) === undefined
      ? {}
      : { tools: toolCalls(delta?.["tool_calls"]) }),
  };
}

function abortFrom(parent: AbortSignal | undefined, controller: AbortController): () => void {
  if (parent === undefined) return () => undefined;
  const abort = (): void => controller.abort(parent.reason);
  if (parent.aborted) abort();
  else parent.addEventListener("abort", abort, { once: true });
  return () => parent.removeEventListener("abort", abort);
}

export function createOpenAICompatibleChatProvider(
  input: ProviderConfigInput,
  dependencies: ProviderDependencies = {},
): OpenAICompatibleChatProvider {
  const config = parseProviderConfig(input);
  const fetchProvider = dependencies.fetch ?? fetch;
  const now = dependencies.now ?? (() => new Date().toISOString());
  const endpoint = new URL("chat/completions", config.baseUrl).toString();

  return {
    async *stream(request): AsyncGenerator<StreamEvent> {
      const controller = new AbortController();
      const detach = abortFrom(request.signal, controller);
      let timedOut = false;
      const timeout = setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, config.timeoutMs);
      let streamId = `chat-${randomUUID()}`;
      let chunkIndex = 0;
      try {
        const response = await fetchProvider(endpoint, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${config.apiKey}`,
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          },
          body: JSON.stringify({
            model: config.model,
            messages: request.messages,
            stream: true,
            ...(request.temperature === undefined ? {} : { temperature: request.temperature }),
            ...(request.maxTokens === undefined ? {} : { max_tokens: request.maxTokens }),
          }),
          signal: controller.signal,
        });
        if (!response.ok) throw responseError(response);

        for await (const data of sseData(response)) {
          if (data === "[DONE]") {
            yield { type: "done", event_id: `${streamId}:${chunkIndex}:done` };
            return;
          }
          const upstream = parseChunk(data);
          streamId = upstream.id ?? streamId;
          const common = {
            id: streamId,
            model: upstream.model ?? config.model,
            timestamp: now(),
          };
          if (upstream.reasoning !== undefined) {
            const chunk: ChatCompletionChunk = {
              ...common,
              chunk_index: chunkIndex,
              delta_reasoning: upstream.reasoning,
            };
            yield {
              type: "reasoning_delta",
              event_id: `${streamId}:${chunkIndex}:reasoning`,
              chunk,
            };
            chunkIndex += 1;
          }
          if (upstream.content !== undefined) {
            const chunk: ChatCompletionChunk = {
              ...common,
              chunk_index: chunkIndex,
              delta_content: upstream.content,
            };
            yield {
              type: "content_delta",
              event_id: `${streamId}:${chunkIndex}:content`,
              chunk,
            };
            chunkIndex += 1;
          }
          if (upstream.tools !== undefined) {
            const chunk: ChatCompletionChunk = {
              ...common,
              chunk_index: chunkIndex,
              delta_tool_calls: upstream.tools,
            };
            yield {
              type: "tool_call_delta",
              event_id: `${streamId}:${chunkIndex}:tool`,
              chunk,
            };
            chunkIndex += 1;
          }
        }
        throw new ProviderRequestError(
          "PROVIDER_UNAVAILABLE",
          "The Provider stream ended without a terminal marker.",
          true,
        );
      } catch (error) {
        if (error instanceof ProviderRequestError) throw error;
        if (timedOut) {
          throw new ProviderRequestError("TIMEOUT", "The Provider request timed out.", true);
        }
        if (request.signal?.aborted === true) {
          throw new ProviderRequestError("CANCELLED", "The Provider request was cancelled.", false);
        }
        throw new ProviderRequestError(
          "PROVIDER_UNAVAILABLE",
          "The Provider request could not be completed.",
          true,
        );
      } finally {
        clearTimeout(timeout);
        detach();
        controller.abort();
      }
    },
  };
}
