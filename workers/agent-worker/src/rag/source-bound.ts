import { createHash } from "node:crypto";

export interface RagQuery {
  readonly question: string;
  readonly courseId: string;
  readonly nodeId: string;
  readonly allowedSourceIds: readonly string[];
  /** Maximum combined excerpt characters. Excerpts are never truncated. */
  readonly maxCharacters?: number;
  readonly maxSources?: number;
}

export interface RagHit {
  readonly sourceId: string;
  readonly courseId: string;
  readonly nodeId: string;
  readonly title: string;
  readonly url: string;
  readonly excerpt: string;
  readonly excerptDigest: string;
  readonly score: number;
}

export interface RagCitation {
  readonly sourceId: string;
  readonly title: string;
  readonly url: string;
  readonly excerptDigest: string;
}

export interface SourceBoundContext {
  readonly question: string;
  readonly prompt: string;
  readonly citations: readonly RagCitation[];
  readonly contextDigest: string;
}

export class NoSourcesError extends Error {
  readonly code = "NO_SOURCES";
  readonly retryable = false;

  constructor() {
    super("No approved, integrity-checked sources are available for this question.");
    this.name = "NoSourcesError";
  }
}

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function safeHttpsUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      url.hostname.length > 0 &&
      url.username.length === 0 &&
      url.password.length === 0
    );
  } catch {
    return false;
  }
}

function validHit(hit: RagHit, query: RagQuery, allowed: ReadonlySet<string>): boolean {
  return (
    allowed.has(hit.sourceId) &&
    hit.courseId === query.courseId &&
    hit.nodeId === query.nodeId &&
    hit.title.trim().length > 0 &&
    safeHttpsUrl(hit.url) &&
    hit.excerpt.trim().length > 0 &&
    /^[a-f0-9]{64}$/.test(hit.excerptDigest) &&
    sha256(hit.excerpt) === hit.excerptDigest &&
    Number.isFinite(hit.score) &&
    hit.score >= 0 &&
    hit.score <= 1
  );
}

function canonicalContext(question: string, hits: readonly RagHit[]): string {
  return JSON.stringify({
    question,
    sources: hits.map((hit) => ({
      source_id: hit.sourceId,
      title: hit.title,
      url: hit.url,
      excerpt: hit.excerpt,
      excerpt_digest: hit.excerptDigest,
    })),
  });
}

export function buildSourceBoundContext(
  query: RagQuery,
  hits: readonly RagHit[],
): SourceBoundContext {
  if (
    query.question.trim().length === 0 ||
    query.courseId.trim().length === 0 ||
    query.nodeId.trim().length === 0
  ) {
    throw new TypeError("RAG question, course, and node must not be empty.");
  }
  const maxCharacters = query.maxCharacters ?? 8_000;
  const maxSources = query.maxSources ?? 8;
  if (!Number.isInteger(maxCharacters) || maxCharacters < 1 || maxCharacters > 100_000) {
    throw new RangeError("RAG context budget must be between 1 and 100000 characters.");
  }
  if (!Number.isInteger(maxSources) || maxSources < 1 || maxSources > 32) {
    throw new RangeError("RAG source count must be between 1 and 32.");
  }

  const allowed = new Set(query.allowedSourceIds);
  if (allowed.size === 0) throw new NoSourcesError();

  const bestBySource = new Map<string, RagHit>();
  for (const hit of hits) {
    if (!validHit(hit, query, allowed)) continue;
    const previous = bestBySource.get(hit.sourceId);
    if (
      previous === undefined ||
      hit.score > previous.score ||
      (hit.score === previous.score && hit.excerptDigest < previous.excerptDigest)
    ) {
      bestBySource.set(hit.sourceId, hit);
    }
  }
  const ranked = [...bestBySource.values()].sort(
    (left, right) => right.score - left.score || left.sourceId.localeCompare(right.sourceId),
  );
  const selected: RagHit[] = [];
  let characters = 0;
  for (const hit of ranked) {
    if (selected.length >= maxSources) break;
    if (characters + hit.excerpt.length > maxCharacters) continue;
    selected.push(hit);
    characters += hit.excerpt.length;
  }
  if (selected.length === 0) throw new NoSourcesError();

  const sourceBlocks = selected
    .map((hit) => `[source:${hit.sourceId}] ${hit.title}\nURL: ${hit.url}\n${hit.excerpt}`)
    .join("\n\n");
  const prompt = [
    "Answer only from the approved sources below.",
    "Cite each factual claim with [source:<source_id>].",
    "If the sources do not support the answer, say that the available sources are insufficient.",
    "",
    `Question: ${query.question}`,
    "",
    sourceBlocks,
  ].join("\n");
  return Object.freeze({
    question: query.question,
    prompt,
    citations: Object.freeze(
      selected.map((hit) =>
        Object.freeze({
          sourceId: hit.sourceId,
          title: hit.title,
          url: hit.url,
          excerptDigest: hit.excerptDigest,
        }),
      ),
    ),
    contextDigest: sha256(canonicalContext(query.question, selected)),
  });
}
