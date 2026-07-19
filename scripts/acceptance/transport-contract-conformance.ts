import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  AgentProposalEnvelope,
  ChatCompletionChunk,
  ChatCompletionRequest,
  ErrorEnvelope,
  SandboxExecutionResponse,
  StreamEvent,
  WorkerJobEnvelope,
} from "../../packages/contracts/src/index.js";

type Expected = "accept" | "reject";
type ParseResult = { success: boolean };
type Schema = { safeParse: (value: unknown) => ParseResult };
type SchemaCase = {
  id: string;
  schema: keyof typeof schemas;
  expected: Expected;
  payload: unknown;
};
type StreamSequence = {
  id: string;
  expected: Expected;
  chunks: unknown[];
};
type FixtureFile = {
  schema_cases: SchemaCase[];
  stream_sequences: StreamSequence[];
};

const schemas = {
  AgentProposalEnvelope,
  ChatCompletionRequest,
  ErrorEnvelope,
  SandboxExecutionResponse,
  StreamEvent,
  WorkerJobEnvelope,
} satisfies Record<string, Schema>;

const fixturePath = fileURLToPath(
  new URL("../../tests/e2e/contracts/fixtures/transport-contract-cases.json", import.meta.url),
);
const fixtures = JSON.parse(readFileSync(fixturePath, "utf8")) as FixtureFile;
const failures: string[] = [];

for (const fixture of fixtures.schema_cases) {
  const accepted = schemas[fixture.schema].safeParse(fixture.payload).success;
  if (accepted !== (fixture.expected === "accept")) {
    failures.push(`${fixture.id}: Zod unexpectedly ${accepted ? "accepted" : "rejected"} payload`);
  }
}

for (const fixture of fixtures.stream_sequences) {
  const chunks = fixture.chunks.map((chunk) => ChatCompletionChunk.safeParse(chunk));
  const accepted =
    chunks.every((chunk) => chunk.success) &&
    chunks.every((chunk, index) => chunk.success && chunk.data.chunk_index === index);
  if (accepted !== (fixture.expected === "accept")) {
    failures.push(`${fixture.id}: Zod ordering gate unexpectedly ${accepted ? "accepted" : "rejected"} sequence`);
  }
}

if (failures.length > 0) {
  throw new Error(`transport contract conformance failed:\n${failures.join("\n")}`);
}

console.log(
  `transport contract conformance passed: ${fixtures.schema_cases.length} schema cases, ` +
    `${fixtures.stream_sequences.length} stream sequences`,
);
