/**
 * FE-020 — typed wrapper for BE-023 practice endpoints.
 *
 *   GET  /api/v1/practice/nodes/{node_id}/questions
 *   POST /api/v1/practice/attempt
 *
 * The generated SDK (@pymentor/api-client) does not yet expose these routes,
 * so we go through the shared `client` from the generated runtime and keep the
 * request/response types here — mirroring the FE-014 onboarding wrapper. When
 * the OpenAPI generator picks the routes up, this wrapper can be retired in
 * favour of the generated functions without changing call sites.
 *
 * Honesty contract (BE-023):
 * - The questions endpoint MUST NOT return `answer_schema` — the correct key
 *   must never reach the browser. This type intentionally omits that field.
 * - The attempt response carries `correct`/`explanation` per question but no
 *   raw answer key; `explanation` is nullable and the UI degrades to "—".
 * - The response returns `evidence_id` but the UI MUST communicate that mastery
 *   is NOT auto-advanced by this endpoint — mastery is decided by the server's
 *   evidence+rules engine, not by a passing score here.
 * - CODE_WRITING-only nodes are unsupported for self-test (HTTP 422); the UI
 *   surfaces that as an honest "use the code lab" branch rather than a bug.
 */
import { client } from "@pymentor/api-client";

/** Question kinds the catalog can store (mirrors backend QuestionTemplateAsset). */
export type PracticeQuestionKind =
  | "MULTIPLE_CHOICE"
  | "CODE_COMPLETION"
  | "CODE_REPAIR"
  | "CODE_WRITING";

/**
 * A practice question as served to the browser. Note the absence of any
 * answer/correctness field — the wire payload is stripped on the server side
 * (BE-023) and this type exists partly to enforce that contract at compile
 * time: callers cannot accidentally read an answer key that was never sent.
 */
export type PracticeQuestion = {
  question_id: string;
  node_id: string;
  kind: PracticeQuestionKind;
  /** Rendered prompt; server instantiates the prompt template before serving. */
  prompt: string;
  /** Answer options for MULTIPLE_CHOICE. Empty for other kinds. */
  options: ReadonlyArray<string>;
};

export type PracticeQuestionsResponse = ReadonlyArray<PracticeQuestion>;

/** One student answer in an attempt submission. */
export type PracticeAnswer = {
  question_id: string;
  /**
   * The option string the student selected (MULTIPLE_CHOICE). Typed as a
   * narrow `string` so the wrapper stays kind-agnostic; the UI only sends this
   * for MULTIPLE_CHOICE.
   */
  selected_answer: string;
};

export type PracticeAttemptRequest = {
  node_id: string;
  answers: ReadonlyArray<PracticeAnswer>;
};

/** Per-question grading returned by the attempt endpoint. */
export type PracticeAttemptPerQuestion = {
  question_id: string;
  correct: boolean;
  /** Optional explanation; may be absent — the UI shows "—" in that case. */
  explanation?: string | null;
};

export type PracticeAttemptResponse = {
  /** 0..1 score fraction. */
  score: number;
  correct_count: number;
  total_count: number;
  per_question: ReadonlyArray<PracticeAttemptPerQuestion>;
  /**
   * Evidence identifier recorded for this attempt. The UI MUST communicate
   * that this is evidence only — mastery is decided server-side, not here.
   */
  evidence_id: string;
};

export type PracticeAttemptOptions = {
  body: PracticeAttemptRequest;
  headers: { Authorization: string; "Idempotency-Key": string };
};

/**
 * Fetch the MULTIPLE_CHOICE practice set for a node.
 *
 * Mirrors the generated SDK's `{ data, error, response }` result shape so
 * callers can use the same error-handling idiom. The endpoint is read-only so
 * no idempotency key is required.
 */
export async function getNodePracticeQuestions({ nodeId, headers }: {
  nodeId: string;
  headers: { Authorization: string };
}) {
  return client.get<PracticeQuestionsResponse, unknown, false>({
    url: `/api/v1/practice/nodes/${encodeURIComponent(nodeId)}/questions`,
    headers,
  });
}

/**
 * Submit a batch of answers for grading.
 *
 * The caller MUST supply an `Idempotency-Key` (use `commandHeaders` from
 * `student-api`). Retries ("再练一次") MUST mint a fresh key so the server
 * records a new evidence event instead of returning the cached result.
 */
export async function submitPracticeAttempt({
  body,
  headers,
}: PracticeAttemptOptions) {
  return client.post<PracticeAttemptResponse, unknown, false>({
    url: "/api/v1/practice/attempt",
    body,
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
  });
}
