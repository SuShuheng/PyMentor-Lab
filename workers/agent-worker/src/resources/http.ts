import { timingSafeEqual } from "node:crypto";

import type { Context } from "hono";

import type { ResourceTypeContract } from "@pymentor/contracts";

import type { SourceBoundContext } from "../rag/source-bound.js";
import { generateResourceBundle } from "./generator.js";

const RESOURCE_TYPES = new Set<ResourceTypeContract>([
  "STRUCTURE_CARD",
  "MICRO_LECTURE",
  "LAYERED_EXERCISE",
  "NOTEBOOK_TASK",
  "TRACE_ANIMATION",
]);

interface ResourceGenerationBody {
  job_id?: unknown;
  learning_need?: unknown;
  resource_types?: unknown;
  context?: unknown;
}

function authorized(value: string | undefined, secret: string): boolean {
  const prefix = "Bearer ";
  if (!value?.startsWith(prefix)) return false;
  const supplied = Buffer.from(value.slice(prefix.length));
  const expected = Buffer.from(secret);
  return supplied.length === expected.length && timingSafeEqual(supplied, expected);
}

function sourceContext(value: unknown): SourceBoundContext | null {
  if (!value || typeof value !== "object") return null;
  const prompt = Reflect.get(value, "prompt");
  const question = Reflect.get(value, "question");
  const contextDigest = Reflect.get(value, "contextDigest");
  const citations = Reflect.get(value, "citations");
  if (
    typeof prompt !== "string" ||
    typeof question !== "string" ||
    typeof contextDigest !== "string" ||
    !/^[a-f0-9]{64}$/.test(contextDigest) ||
    !Array.isArray(citations) ||
    citations.length === 0 ||
    citations.length > 32
  ) {
    return null;
  }
  const normalized = citations.flatMap((citation) => {
    if (!citation || typeof citation !== "object") return [];
    const sourceId = Reflect.get(citation, "sourceId");
    const title = Reflect.get(citation, "title");
    const url = Reflect.get(citation, "url");
    const excerptDigest = Reflect.get(citation, "excerptDigest");
    return typeof sourceId === "string" &&
      typeof title === "string" &&
      typeof url === "string" &&
      typeof excerptDigest === "string"
      ? [{ sourceId, title, url, excerptDigest }]
      : [];
  });
  if (normalized.length !== citations.length) return null;
  return { citations: normalized, contextDigest, prompt, question };
}

export function createResourceGenerationHandler(internalSecret: string) {
  return async (context: Context): Promise<Response> => {
    if (!authorized(context.req.header("authorization"), internalSecret)) {
      return context.json({ code: "UNAUTHORIZED" }, 401);
    }
    let body: ResourceGenerationBody;
    try {
      body = (await context.req.json()) as ResourceGenerationBody;
    } catch {
      return context.json({ code: "INVALID_JSON" }, 400);
    }
    const resourceTypes = Array.isArray(body.resource_types)
      ? body.resource_types.filter(
          (item): item is ResourceTypeContract =>
            typeof item === "string" && RESOURCE_TYPES.has(item as ResourceTypeContract),
        )
      : [];
    const boundContext = sourceContext(body.context);
    if (
      typeof body.job_id !== "string" ||
      typeof body.learning_need !== "string" ||
      resourceTypes.length === 0 ||
      resourceTypes.length !== (body.resource_types as unknown[] | undefined)?.length ||
      !boundContext
    ) {
      return context.json({ code: "INVALID_RESOURCE_REQUEST" }, 422);
    }

    try {
      const result = await generateResourceBundle(
        {
          context: boundContext,
          jobId: body.job_id,
          learningNeed: body.learning_need,
          resourceTypes,
        },
        {
          sink: { async stage() {} },
          text: {
            async generate() {
              throw new Error("Provider unavailable; use the governed bounded fallback.");
            },
          },
        },
      );
      return context.json(
        {
          artifacts: result.artifacts.map((artifact) => ({
            content_base64: Buffer.from(artifact.content).toString("base64"),
            content_digest: artifact.contentDigest,
            context_digest: artifact.contextDigest,
            fallback_used: artifact.fallbackUsed,
            mime_type: artifact.mimeType,
            resource_type: artifact.resourceType,
            source_ids: artifact.sourceIds,
          })),
          job_id: result.jobId,
          status: result.status,
        },
        200,
      );
    } catch {
      return context.json({ code: "RESOURCE_GENERATION_FAILED" }, 503);
    }
  };
}
