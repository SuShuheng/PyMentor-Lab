import { describe, expect, it, vi } from "vitest";

import { ProviderRequestError } from "./openai-compatible.js";
import { createProviderCapabilities } from "./capabilities.js";

const config = {
  baseUrl: "https://provider.example/v1",
  apiKey: "secret-provider-key",
  model: "capability-model",
};

describe("non-chat Provider capability adapters", () => {
  it("normalizes generated images without downloading untrusted URLs", async () => {
    const fetch = vi.fn().mockResolvedValue(
      Response.json({
        created: 1,
        data: [{ b64_json: "aW1hZ2UtYnl0ZXM=", revised_prompt: "safe diagram" }],
      }),
    );
    const providers = createProviderCapabilities(config, { fetch });

    const image = await providers.image.generate({
      prompt: "A Python loop diagram",
      size: "1024x1024",
    });

    expect(image).toEqual({
      bytes: new Uint8Array(Buffer.from("image-bytes")),
      contentType: "image/png",
      revisedPrompt: "safe diagram",
      model: "capability-model",
    });
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toMatchObject({
      model: "capability-model",
      prompt: "A Python loop diagram",
      response_format: "b64_json",
    });
  });

  it("normalizes moderation decisions and category scores", async () => {
    const fetch = vi.fn().mockResolvedValue(
      Response.json({
        results: [
          {
            flagged: true,
            categories: { violence: true, sexual: false },
            category_scores: { violence: 0.91, sexual: 0.02 },
          },
        ],
      }),
    );
    const providers = createProviderCapabilities(config, { fetch });

    await expect(providers.moderation.review({ text: "unsafe text" })).resolves.toEqual({
      allowed: false,
      categories: { sexual: false, violence: true },
      scores: { sexual: 0.02, violence: 0.91 },
      model: "capability-model",
    });
  });

  it("preserves input order and rejects inconsistent embedding dimensions", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({
          data: [
            { index: 1, embedding: [0.3, 0.4] },
            { index: 0, embedding: [0.1, 0.2] },
          ],
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          data: [
            { index: 0, embedding: [0.1] },
            { index: 1, embedding: [0.2, 0.3] },
          ],
        }),
      );
    const providers = createProviderCapabilities(config, { fetch });

    await expect(providers.embedding.embed({ inputs: ["first", "second"] })).resolves.toEqual({
      vectors: [
        [0.1, 0.2],
        [0.3, 0.4],
      ],
      dimensions: 2,
      model: "capability-model",
    });
    await expect(
      providers.embedding.embed({ inputs: ["first", "second"] }),
    ).rejects.toMatchObject({ code: "PROVIDER_UNAVAILABLE", retryable: true });
  });

  it("returns bounded TTS bytes and rejects oversized audio", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(new Uint8Array([1, 2, 3]), {
          headers: { "content-type": "audio/mpeg" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(new Uint8Array(9), {
          headers: { "content-type": "audio/mpeg", "content-length": "9" },
        }),
      );
    const providers = createProviderCapabilities(config, { fetch, maxAudioBytes: 8 });

    await expect(
      providers.tts.synthesize({ text: "解释循环", voice: "xiaoyan", format: "mp3" }),
    ).resolves.toEqual({ bytes: new Uint8Array([1, 2, 3]), contentType: "audio/mpeg" });
    await expect(
      providers.tts.synthesize({ text: "too large", voice: "xiaoyan", format: "mp3" }),
    ).rejects.toBeInstanceOf(ProviderRequestError);
  });

  it("uses stable errors and never echoes an upstream response body", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response("secret-provider-key and private upstream details", { status: 503 }),
    );
    const providers = createProviderCapabilities(config, { fetch });

    const call = providers.moderation.review({ text: "hello" });
    await expect(call).rejects.toMatchObject({
      code: "PROVIDER_UNAVAILABLE",
      retryable: true,
    });
    await expect(call).rejects.not.toThrow(/secret-provider-key|private upstream details/);
  });
});
