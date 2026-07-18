/**
 * Streaming contracts: OpenAI-compatible chat chunks and the SSE event union
 * rendered by student/admin tutoring surfaces.
 *
 * Field names MUST stay in lock-step with `backend/app/contracts/streaming.py`.
 * See PRD REQ-P0-012 and CONTRACT.md "Renderer-facing models and events".
 */

import { z } from "zod";

export const ChatMessage = z.object({
  role: z.enum(["system", "user", "assistant", "tool"]),
  content: z.string().min(1).max(20_000),
});
export type ChatMessage = z.infer<typeof ChatMessage>;

export const ChatCompletionRequest = z.object({
  course_id: z.string().uuid(),
  node_id: z.string().uuid(),
  messages: z.array(ChatMessage).min(1).max(64),
  stream: z.literal(true).default(true),
});
export type ChatCompletionRequest = z.infer<typeof ChatCompletionRequest>;

/** A single tool-call delta carried on the streaming response. */
export const ToolCallDelta = z.object({
  /** Index groups pieces of the same logical tool call across chunks. */
  index: z.number().int().nonnegative(),
  id: z.string().optional(),
  name: z.string().optional(),
  arguments: z.string().optional(),
});
export type ToolCallDelta = z.infer<typeof ToolCallDelta>;

/**
 * OpenAI Chat Completions-compatible streaming chunk. Carries content,
 * reasoning_content (thinking models), and tool_calls as separate streams.
 */
export const ChatCompletionChunk = z.object({
  id: z.string().min(1),
  /** Monotonic chunk index for ordering and reconnect/replay by event id. */
  chunk_index: z.number().int().nonnegative(),
  delta_content: z.string().optional(),
  delta_reasoning: z.string().optional(),
  delta_tool_calls: z.array(ToolCallDelta).optional(),
  model: z.string().optional(),
  /** ISO-8601 timestamp in UTC. */
  timestamp: z.string().min(1),
});
export type ChatCompletionChunk = z.infer<typeof ChatCompletionChunk>;

/**
 * Discriminated union of all SSE events a tutoring/job stream may emit.
 * The renderer preserves order per stream and tolerates reconnect/replay
 * by event id. Required discriminants per CONTRACT.md:
 * content_delta, reasoning_delta, tool_call_delta, progress, error, done.
 */
export const StreamEvent = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("content_delta"),
    event_id: z.string().min(1),
    chunk: ChatCompletionChunk,
  }),
  z.object({
    type: z.literal("reasoning_delta"),
    event_id: z.string().min(1),
    chunk: ChatCompletionChunk,
  }),
  z.object({
    type: z.literal("tool_call_delta"),
    event_id: z.string().min(1),
    chunk: ChatCompletionChunk,
  }),
  z.object({
    type: z.literal("progress"),
    event_id: z.string().min(1),
    message: z.string().optional(),
    percent: z.number().min(0).max(100).optional(),
  }),
  z.object({
    type: z.literal("error"),
    event_id: z.string().min(1),
    // Inline import-safe envelope reference (kept flat for serializability).
    error: z.object({
      code: z.string().min(1),
      message: z.string().min(1),
      trace_id: z.string().min(1),
      retryable: z.boolean(),
    }),
  }),
  z.object({
    type: z.literal("done"),
    event_id: z.string().min(1),
  }),
]);
export type StreamEvent = z.infer<typeof StreamEvent>;
