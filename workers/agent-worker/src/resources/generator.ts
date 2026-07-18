import { createHash } from "node:crypto";

import type { ResourceTypeContract } from "@pymentor/contracts";

import type { SourceBoundContext } from "../rag/source-bound.js";

const PRIORITY: readonly ResourceTypeContract[] = Object.freeze([
  "STRUCTURE_CARD",
  "MICRO_LECTURE",
  "LAYERED_EXERCISE",
  "NOTEBOOK_TASK",
  "TRACE_ANIMATION",
]);

export interface ResourceGenerationRequest {
  readonly jobId: string;
  readonly learningNeed: string;
  readonly context: SourceBoundContext;
  readonly resourceTypes: readonly ResourceTypeContract[];
}

export interface GeneratedResourceArtifact {
  readonly resourceType: ResourceTypeContract;
  readonly content: Uint8Array;
  readonly mimeType: string;
  readonly sourceIds: readonly string[];
  readonly contextDigest: string;
  readonly contentDigest: string;
  readonly fallbackUsed: boolean;
}

export interface ResourceGenerationProgress {
  readonly jobId: string;
  readonly status: "PARTIAL_READY" | "READY";
  readonly completed: number;
  readonly total: number;
  readonly percent: number;
  readonly resourceType: ResourceTypeContract;
}

export interface ResourceGenerationResult {
  readonly jobId: string;
  readonly status: "READY";
  readonly artifacts: readonly GeneratedResourceArtifact[];
}

export interface TextGenerationPort {
  generate(prompt: string): Promise<string>;
}

export interface ResourceArtifactSink {
  stage(artifact: GeneratedResourceArtifact): Promise<void>;
}

export interface ResourceGeneratorDependencies {
  readonly text: TextGenerationPort;
  readonly sink: ResourceArtifactSink;
  readonly onProgress?: (event: ResourceGenerationProgress) => void | Promise<void>;
}

export class ResourceGenerationError extends Error {
  constructor(
    readonly code: "INVALID_RESOURCE_REQUEST" | "RESOURCE_STAGE_FAILED",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "ResourceGenerationError";
  }
}

function sha256(content: Uint8Array): string {
  return createHash("sha256").update(content).digest("hex");
}

function encode(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function citations(context: SourceBoundContext): readonly string[] {
  return context.citations.map((citation) => citation.sourceId);
}

function citationLabels(context: SourceBoundContext): string {
  return context.citations.map((citation) => `[source:${citation.sourceId}]`).join(" ");
}

function jsonArtifact(value: unknown): Uint8Array {
  return encode(JSON.stringify(value, null, 2));
}

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function structureCard(request: ResourceGenerationRequest): Uint8Array {
  return jsonArtifact({
    schema_version: 1,
    kind: "STRUCTURE_CARD",
    title: "Python concept structure card",
    learning_need: request.learningNeed,
    checkpoints: ["state before iteration", "current item", "state after iteration"],
    sources: citations(request.context),
  });
}

function layeredExercise(request: ResourceGenerationRequest): Uint8Array {
  return jsonArtifact({
    schema_version: 1,
    kind: "LAYERED_EXERCISE",
    learning_need: request.learningNeed,
    layers: [
      { level: 1, prompt: "Trace one iteration and name the current value." },
      { level: 2, prompt: "Repair an exclusive stop-boundary error." },
      { level: 3, prompt: "Transfer the loop pattern to a new iterable." },
    ],
    sources: citations(request.context),
  });
}

function notebookTask(request: ResourceGenerationRequest): Uint8Array {
  const labels = citationLabels(request.context);
  return jsonArtifact({
    nbformat: 4,
    nbformat_minor: 5,
    metadata: { pymentor: { context_digest: request.context.contextDigest } },
    cells: [
      {
        cell_type: "markdown",
        metadata: {},
        source: [`# Loop investigation\n`, `${request.learningNeed}\n`, `Sources: ${labels}`],
      },
      {
        cell_type: "code",
        execution_count: null,
        metadata: {},
        outputs: [],
        source: ["# Predict the next value before running.\n", "for value in range(3):\n", "    print(value)\n"],
      },
    ],
  });
}

function traceAnimation(request: ResourceGenerationRequest): Uint8Array {
  const need = escapeXml(request.learningNeed);
  const labels = escapeXml(citationLabels(request.context));
  return encode(
    [
      '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" role="img"',
      ' aria-labelledby="title description">',
      '<title id="title">Deterministic Python loop trace</title>',
      `<desc id="description">${need}; ${labels}</desc>`,
      '<rect width="960" height="540" fill="#0f172a"/>',
      '<text x="48" y="80" fill="#f8fafc" font-size="28">Loop state trace</text>',
      '<g fill="#38bdf8" font-size="22">',
      '<text x="80" y="180">value = 0</text>',
      '<text x="360" y="180">value = 1</text>',
      '<text x="640" y="180">value = 2</text>',
      '</g>',
      '<path d="M200 170 H330 M480 170 H610" stroke="#fbbf24" stroke-width="6"/>',
      `<text x="48" y="480" fill="#cbd5e1" font-size="16">${labels}</text>`,
      "</svg>",
    ].join(""),
  );
}

async function microLecture(
  request: ResourceGenerationRequest,
  text: TextGenerationPort,
): Promise<{ content: Uint8Array; fallbackUsed: boolean }> {
  const labels = citationLabels(request.context);
  try {
    const generated = await text.generate(
      [
        request.context.prompt,
        "",
        `Learning need: ${request.learningNeed}`,
        "Write a concise university-level Python micro-lecture with source citations.",
      ].join("\n"),
    );
    if (generated.trim().length === 0) throw new Error("empty provider output");
    const cited = citations(request.context).every((id) => generated.includes(`[source:${id}]`));
    const content = cited ? generated : `${generated}\n\nSources: ${labels}`;
    return { content: encode(content), fallbackUsed: false };
  } catch {
    return {
      content: encode(
        [
          "# Python micro-lecture",
          "",
          request.learningNeed,
          "",
          "Use the governed reference to inspect iteration state and exclusive boundaries.",
          "",
          `Sources: ${labels}`,
        ].join("\n"),
      ),
      fallbackUsed: true,
    };
  }
}

async function buildArtifact(
  resourceType: ResourceTypeContract,
  request: ResourceGenerationRequest,
  text: TextGenerationPort,
): Promise<GeneratedResourceArtifact> {
  let content: Uint8Array;
  let mimeType: string;
  let fallbackUsed = false;
  switch (resourceType) {
    case "STRUCTURE_CARD":
      content = structureCard(request);
      mimeType = "application/json";
      break;
    case "MICRO_LECTURE": {
      const lecture = await microLecture(request, text);
      content = lecture.content;
      fallbackUsed = lecture.fallbackUsed;
      mimeType = "text/markdown";
      break;
    }
    case "LAYERED_EXERCISE":
      content = layeredExercise(request);
      mimeType = "application/json";
      break;
    case "NOTEBOOK_TASK":
      content = notebookTask(request);
      mimeType = "application/x-ipynb+json";
      break;
    case "TRACE_ANIMATION":
      content = traceAnimation(request);
      mimeType = "image/svg+xml";
      break;
  }
  return Object.freeze({
    resourceType,
    content,
    mimeType,
    sourceIds: Object.freeze([...citations(request.context)]),
    contextDigest: request.context.contextDigest,
    contentDigest: sha256(content),
    fallbackUsed,
  });
}

export async function generateResourceBundle(
  request: ResourceGenerationRequest,
  dependencies: ResourceGeneratorDependencies,
): Promise<ResourceGenerationResult> {
  const requested = new Set(request.resourceTypes);
  if (
    request.jobId.trim().length === 0 ||
    request.learningNeed.trim().length === 0 ||
    requested.size === 0 ||
    requested.size !== request.resourceTypes.length ||
    [...requested].some((item) => !PRIORITY.includes(item))
  ) {
    throw new ResourceGenerationError(
      "INVALID_RESOURCE_REQUEST",
      "Resource request must contain a job, learning need, and unique supported resource types.",
    );
  }
  if (request.context.citations.length === 0) {
    throw new ResourceGenerationError(
      "INVALID_RESOURCE_REQUEST",
      "Resource generation requires approved sources.",
    );
  }
  const ordered = PRIORITY.filter((item) => requested.has(item));
  const artifacts: GeneratedResourceArtifact[] = [];
  for (const resourceType of ordered) {
    const artifact = await buildArtifact(resourceType, request, dependencies.text);
    try {
      await dependencies.sink.stage(artifact);
    } catch (error) {
      throw new ResourceGenerationError(
        "RESOURCE_STAGE_FAILED",
        "The generated resource could not be staged.",
        { cause: error },
      );
    }
    artifacts.push(artifact);
    const completed = artifacts.length;
    await dependencies.onProgress?.({
      jobId: request.jobId,
      status: completed === ordered.length ? "READY" : "PARTIAL_READY",
      completed,
      total: ordered.length,
      percent: Math.floor((completed * 100) / ordered.length),
      resourceType,
    });
  }
  return Object.freeze({
    jobId: request.jobId,
    status: "READY",
    artifacts: Object.freeze(artifacts),
  });
}
