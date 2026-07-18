import {
  ProviderRequestError,
  parseProviderConfig,
  type ProviderConfigInput,
} from "./openai-compatible.js";

export interface ImageGenerationRequest {
  readonly prompt: string;
  readonly size?: "256x256" | "512x512" | "1024x1024";
  readonly signal?: AbortSignal;
}

export interface GeneratedImage {
  readonly bytes: Uint8Array;
  readonly contentType: "image/png";
  readonly revisedPrompt?: string;
  readonly model: string;
}

export interface ModerationRequest {
  readonly text: string;
  readonly signal?: AbortSignal;
}

export interface ModerationDecision {
  readonly allowed: boolean;
  readonly categories: Readonly<Record<string, boolean>>;
  readonly scores: Readonly<Record<string, number>>;
  readonly model: string;
}

export interface EmbeddingRequest {
  readonly inputs: readonly string[];
  readonly signal?: AbortSignal;
}

export interface EmbeddingResult {
  readonly vectors: readonly (readonly number[])[];
  readonly dimensions: number;
  readonly model: string;
}

export interface SpeechRequest {
  readonly text: string;
  readonly voice: string;
  readonly format: "mp3" | "wav" | "opus" | "aac" | "flac" | "pcm";
  readonly signal?: AbortSignal;
}

export interface SpeechResult {
  readonly bytes: Uint8Array;
  readonly contentType: string;
}

export interface ProviderCapabilities {
  readonly image: { generate(request: ImageGenerationRequest): Promise<GeneratedImage> };
  readonly moderation: { review(request: ModerationRequest): Promise<ModerationDecision> };
  readonly embedding: { embed(request: EmbeddingRequest): Promise<EmbeddingResult> };
  readonly tts: { synthesize(request: SpeechRequest): Promise<SpeechResult> };
}

type FetchLike = (input: string | URL, init?: RequestInit) => Promise<Response>;

export interface CapabilityDependencies {
  readonly fetch?: FetchLike;
  readonly maxImageBytes?: number;
  readonly maxAudioBytes?: number;
}

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord | undefined {
  return typeof value === "object" && value !== null ? (value as UnknownRecord) : undefined;
}

function responseError(response: Response): ProviderRequestError {
  if (response.status === 429) {
    const seconds = Number(response.headers.get("retry-after"));
    return new ProviderRequestError(
      "RATE_LIMITED",
      "The Provider rate limit was reached.",
      true,
      Number.isFinite(seconds) && seconds >= 0 ? Math.round(seconds * 1_000) : undefined,
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

function validateText(value: string, name: string, maximum: number): void {
  if (value.trim().length === 0 || value.length > maximum) {
    throw new ProviderRequestError(
      "CONTENT_REJECTED",
      `${name} must contain between 1 and ${maximum} characters.`,
      false,
    );
  }
}

function attachAbort(parent: AbortSignal | undefined, controller: AbortController): () => void {
  if (parent === undefined) return () => undefined;
  const abort = (): void => controller.abort(parent.reason);
  if (parent.aborted) abort();
  else parent.addEventListener("abort", abort, { once: true });
  return () => parent.removeEventListener("abort", abort);
}

function contentLength(response: Response): number | undefined {
  const value = response.headers.get("content-length");
  if (value === null) return undefined;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : undefined;
}

function boundedBytes(response: Response, maximum: number, capability: string): Promise<Uint8Array> {
  const declared = contentLength(response);
  if (declared !== undefined && declared > maximum) {
    throw new ProviderRequestError(
      "PROVIDER_UNAVAILABLE",
      `The Provider ${capability} response exceeded the configured size limit.`,
      false,
    );
  }
  return response.arrayBuffer().then((buffer) => {
    if (buffer.byteLength > maximum) {
      throw new ProviderRequestError(
        "PROVIDER_UNAVAILABLE",
        `The Provider ${capability} response exceeded the configured size limit.`,
        false,
      );
    }
    return new Uint8Array(buffer);
  });
}

function jsonRecord(value: unknown): UnknownRecord {
  const result = record(value);
  if (result === undefined) {
    throw new ProviderRequestError(
      "PROVIDER_UNAVAILABLE",
      "The Provider returned an invalid JSON response.",
      true,
    );
  }
  return result;
}

function booleanMap(value: unknown): Readonly<Record<string, boolean>> {
  const source = jsonRecord(value);
  const output: Record<string, boolean> = {};
  for (const key of Object.keys(source).sort()) {
    const item = source[key];
    if (typeof item !== "boolean") {
      throw new ProviderRequestError(
        "PROVIDER_UNAVAILABLE",
        "The Provider returned invalid moderation categories.",
        true,
      );
    }
    output[key] = item;
  }
  return Object.freeze(output);
}

function numberMap(value: unknown): Readonly<Record<string, number>> {
  const source = jsonRecord(value);
  const output: Record<string, number> = {};
  for (const key of Object.keys(source).sort()) {
    const item = source[key];
    if (typeof item !== "number" || !Number.isFinite(item) || item < 0 || item > 1) {
      throw new ProviderRequestError(
        "PROVIDER_UNAVAILABLE",
        "The Provider returned invalid moderation scores.",
        true,
      );
    }
    output[key] = item;
  }
  return Object.freeze(output);
}

export function createProviderCapabilities(
  input: ProviderConfigInput,
  dependencies: CapabilityDependencies = {},
): ProviderCapabilities {
  const config = parseProviderConfig(input);
  const fetchProvider = dependencies.fetch ?? fetch;
  const maxImageBytes = dependencies.maxImageBytes ?? 10 * 1_024 * 1_024;
  const maxAudioBytes = dependencies.maxAudioBytes ?? 20 * 1_024 * 1_024;

  const invoke = async (
    path: string,
    body: UnknownRecord,
    signal: AbortSignal | undefined,
    accept: string,
  ): Promise<Response> => {
    const controller = new AbortController();
    const detach = attachAbort(signal, controller);
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, config.timeoutMs);
    try {
      const response = await fetchProvider(new URL(path, config.baseUrl), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${config.apiKey}`,
          "Content-Type": "application/json",
          Accept: accept,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!response.ok) throw responseError(response);
      return response;
    } catch (error) {
      if (error instanceof ProviderRequestError) throw error;
      if (timedOut) {
        throw new ProviderRequestError("TIMEOUT", "The Provider request timed out.", true);
      }
      if (signal?.aborted === true) {
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
    }
  };

  const json = async (
    path: string,
    body: UnknownRecord,
    signal?: AbortSignal,
  ): Promise<UnknownRecord> => {
    const response = await invoke(path, body, signal, "application/json");
    try {
      return jsonRecord(await response.json());
    } catch (error) {
      if (error instanceof ProviderRequestError) throw error;
      throw new ProviderRequestError(
        "PROVIDER_UNAVAILABLE",
        "The Provider returned invalid JSON.",
        true,
      );
    }
  };

  return {
    image: {
      async generate(request): Promise<GeneratedImage> {
        validateText(request.prompt, "Image prompt", 8_000);
        const payload = await json(
          "images/generations",
          {
            model: config.model,
            prompt: request.prompt,
            response_format: "b64_json",
            ...(request.size === undefined ? {} : { size: request.size }),
          },
          request.signal,
        );
        const data = payload["data"];
        const image = Array.isArray(data) ? record(data[0]) : undefined;
        const encoded = image?.["b64_json"];
        if (typeof encoded !== "string" || encoded.length === 0) {
          throw new ProviderRequestError(
            "PROVIDER_UNAVAILABLE",
            "The Provider returned no inline image.",
            true,
          );
        }
        const bytes = new Uint8Array(Buffer.from(encoded, "base64"));
        if (bytes.byteLength === 0 || bytes.byteLength > maxImageBytes) {
          throw new ProviderRequestError(
            "PROVIDER_UNAVAILABLE",
            "The Provider image response exceeded the configured size limit.",
            false,
          );
        }
        const revisedPrompt = image?.["revised_prompt"];
        return {
          bytes,
          contentType: "image/png",
          ...(typeof revisedPrompt === "string" ? { revisedPrompt } : {}),
          model: config.model,
        };
      },
    },
    moderation: {
      async review(request): Promise<ModerationDecision> {
        validateText(request.text, "Moderation text", 100_000);
        const payload = await json(
          "moderations",
          { model: config.model, input: request.text },
          request.signal,
        );
        const results = payload["results"];
        const result = Array.isArray(results) ? record(results[0]) : undefined;
        if (typeof result?.["flagged"] !== "boolean") {
          throw new ProviderRequestError(
            "PROVIDER_UNAVAILABLE",
            "The Provider returned an invalid moderation decision.",
            true,
          );
        }
        return {
          allowed: !result["flagged"],
          categories: booleanMap(result["categories"]),
          scores: numberMap(result["category_scores"]),
          model: config.model,
        };
      },
    },
    embedding: {
      async embed(request): Promise<EmbeddingResult> {
        if (request.inputs.length === 0 || request.inputs.length > 128) {
          throw new ProviderRequestError(
            "CONTENT_REJECTED",
            "Embedding requests must contain between 1 and 128 inputs.",
            false,
          );
        }
        request.inputs.forEach((item) => validateText(item, "Embedding input", 20_000));
        const payload = await json(
          "embeddings",
          { model: config.model, input: request.inputs },
          request.signal,
        );
        const data = payload["data"];
        if (!Array.isArray(data) || data.length !== request.inputs.length) {
          throw new ProviderRequestError(
            "PROVIDER_UNAVAILABLE",
            "The Provider returned an invalid embedding count.",
            true,
          );
        }
        const ordered: number[][] = Array.from({ length: data.length });
        for (const item of data) {
          const row = record(item);
          const index = row?.["index"];
          const vector = row?.["embedding"];
          if (
            typeof index !== "number" ||
            !Number.isInteger(index) ||
            index < 0 ||
            index >= data.length ||
            ordered[index] !== undefined ||
            !Array.isArray(vector) ||
            vector.length === 0 ||
            vector.some((value) => typeof value !== "number" || !Number.isFinite(value))
          ) {
            throw new ProviderRequestError(
              "PROVIDER_UNAVAILABLE",
              "The Provider returned invalid embeddings.",
              true,
            );
          }
          ordered[index] = vector as number[];
        }
        const dimensions = ordered[0]?.length ?? 0;
        if (dimensions === 0 || ordered.some((vector) => vector.length !== dimensions)) {
          throw new ProviderRequestError(
            "PROVIDER_UNAVAILABLE",
            "The Provider returned inconsistent embedding dimensions.",
            true,
          );
        }
        return { vectors: ordered, dimensions, model: config.model };
      },
    },
    tts: {
      async synthesize(request): Promise<SpeechResult> {
        validateText(request.text, "Speech text", 20_000);
        validateText(request.voice, "Speech voice", 128);
        const response = await invoke(
          "audio/speech",
          {
            model: config.model,
            input: request.text,
            voice: request.voice,
            response_format: request.format,
          },
          request.signal,
          "audio/*",
        );
        return {
          bytes: await boundedBytes(response, maxAudioBytes, "audio"),
          contentType: response.headers.get("content-type")?.split(";")[0] ?? "application/octet-stream",
        };
      },
    },
  };
}
