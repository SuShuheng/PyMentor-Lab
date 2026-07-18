import { describe, expect, it, vi } from "vitest";

import {
  createOpenAICompatibleChatProvider,
  parseProviderConfig,
} from "./openai-compatible.js";

function streamResponse(lines: readonly string[]): Response {
  return new Response(lines.join("\n"), {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

describe("OpenAI-compatible provider configuration", () => {
  it("allows HTTPS and loopback HTTP without exposing the API key", () => {
    const remote = parseProviderConfig({
      baseUrl: "https://provider.example/v1/",
      apiKey: "secret-provider-key",
      model: "reasoning-model",
      timeoutMs: 5_000,
    });
    const local = parseProviderConfig({
      baseUrl: "http://127.0.0.1:11434/v1",
      apiKey: "local-development-key",
      model: "local-model",
    });

    expect(remote.baseUrl).toBe("https://provider.example/v1/");
    expect(local.baseUrl).toBe("http://127.0.0.1:11434/v1/");
    expect(JSON.stringify(remote)).not.toContain("secret-provider-key");
  });

  it.each([
    "http://provider.example/v1",
    "https://user:password@provider.example/v1",
    "file:///tmp/provider",
  ])("rejects an unsafe Provider URL: %s", (baseUrl) => {
    expect(() =>
      parseProviderConfig({ baseUrl, apiKey: "secret-provider-key", model: "model" }),
    ).toThrow(/Provider base URL/);
  });
});

describe("OpenAI-compatible chat streaming", () => {
  it("maps reasoning, content, tool calls, and the terminal marker in order", async () => {
    const fetch = vi.fn().mockResolvedValue(
      streamResponse([
        'data: {"id":"chat-1","model":"spark-x","choices":[{"delta":{"reasoning_content":"先分析"}}]}',
        "",
        'data: {"id":"chat-1","model":"spark-x","choices":[{"delta":{"content":"答案"}}]}',
        "",
        'data: {"id":"chat-1","model":"spark-x","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"knowledge_search","arguments":"{\\"q\\":\\"循环\\"}"}}]}}]}',
        "",
        "data: [DONE]",
        "",
      ]),
    );
    const provider = createOpenAICompatibleChatProvider(
      {
        baseUrl: "https://provider.example/v1",
        apiKey: "secret-provider-key",
        model: "spark-x",
      },
      { fetch, now: () => "2026-07-18T00:00:00Z" },
    );

    const events = [];
    for await (const event of provider.stream({
      messages: [{ role: "user", content: "解释循环" }],
    })) {
      events.push(event);
    }

    expect(events.map((event) => event.type)).toEqual([
      "reasoning_delta",
      "content_delta",
      "tool_call_delta",
      "done",
    ]);
    expect(events[0]).toMatchObject({
      event_id: "chat-1:0:reasoning",
      chunk: { chunk_index: 0, delta_reasoning: "先分析" },
    });
    expect(events[1]).toMatchObject({
      event_id: "chat-1:1:content",
      chunk: { chunk_index: 1, delta_content: "答案" },
    });
    expect(events[2]).toMatchObject({
      event_id: "chat-1:2:tool",
      chunk: {
        chunk_index: 2,
        delta_tool_calls: [
          {
            index: 0,
            id: "call-1",
            name: "knowledge_search",
            arguments: '{"q":"循环"}',
          },
        ],
      },
    });
    expect(events[3]).toEqual({ type: "done", event_id: "chat-1:3:done" });
    expect(fetch).toHaveBeenCalledWith(
      "https://provider.example/v1/chat/completions",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer secret-provider-key" }),
      }),
    );
    const request = JSON.parse(String(fetch.mock.calls[0]?.[1]?.body)) as Record<string, unknown>;
    expect(request).toMatchObject({ model: "spark-x", stream: true });
  });

  it("classifies rate limits without leaking the provider response or key", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response("upstream included secret-provider-key", {
        status: 429,
        headers: { "retry-after": "2" },
      }),
    );
    const provider = createOpenAICompatibleChatProvider(
      {
        baseUrl: "https://provider.example/v1",
        apiKey: "secret-provider-key",
        model: "spark-x",
      },
      { fetch },
    );

    const consume = async (): Promise<void> => {
      for await (const _event of provider.stream({
        messages: [{ role: "user", content: "hello" }],
      })) {
        // Consume the stream to surface the request error.
      }
    };

    await expect(consume()).rejects.toMatchObject({
      code: "RATE_LIMITED",
      retryable: true,
      retryAfterMs: 2_000,
    });
    await expect(consume()).rejects.not.toThrow(/secret-provider-key/);
  });

  it("aborts a stalled request at the configured deadline", async () => {
    vi.useFakeTimers();
    try {
      const fetch = vi.fn((_url: string | URL, init?: RequestInit) => {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("aborted", "AbortError"));
          });
        });
      });
      const provider = createOpenAICompatibleChatProvider(
        {
          baseUrl: "https://provider.example/v1",
          apiKey: "secret-provider-key",
          model: "spark-x",
          timeoutMs: 50,
        },
        { fetch },
      );
      const consume = async (): Promise<void> => {
        for await (const _event of provider.stream({
          messages: [{ role: "user", content: "hello" }],
        })) {
          // Consume the stream to surface the timeout.
        }
      };

      const rejection = expect(consume()).rejects.toMatchObject({
        code: "TIMEOUT",
        retryable: true,
      });
      await vi.advanceTimersByTimeAsync(50);

      await rejection;
    } finally {
      vi.useRealTimers();
    }
  });
});
