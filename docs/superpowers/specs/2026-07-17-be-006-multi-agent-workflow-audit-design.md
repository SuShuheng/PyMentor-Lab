# BE-006 Multi-Agent Workflow and Audit Design

**Status:** Approved derivative of the frozen PyMentor Lab V1.0 design and
backend contract, 2026-07-17.

## Goal and boundary

BE-006 turns the Worker bootstrap into a real, replayable LangGraph.js workflow.
It provides six independently governed nodes, versioned Redis jobs/events,
idempotent processing, native checkpoints, and durable Agent/tool audit records.
The Worker only emits schema-validated proposals and progress; FastAPI remains
the sole authority that commits profiles, paths, mastery, reviews, or published
resources.

Real Spark/TTS/image/OCR/moderation/embedding adapters, RAG, object storage, and
resource publication belong to BE-007. BE-006 defines injectable tool/provider
ports and deterministic test/fallback adapters so the orchestration is complete
without crossing that task boundary.

## Considered approaches

1. **Modular ports + BullMQ + native Redis checkpoints (selected).** Six node
   definitions share an execution shell but retain separate schemas and policy.
   BullMQ supplies an at-least-once queue, LangGraph supplies the explicit graph,
   RedisSaver supplies checkpoints, and a versioned Redis stream carries audit
   events to FastAPI. This is the only approach that satisfies replay and keeps
   formal-state authority in FastAPI.
2. **In-memory LangGraph checkpoints.** Simpler, but restart loses replay state
   and duplicate deliveries can repeat provider/tool side effects. It fails the
   frozen durability requirement.
3. **Worker writes PostgreSQL Agent tables directly.** Durable, but violates the
   contract that the Worker has no direct formal-state authority and couples the
   TypeScript process to Python-owned persistence.

## Runtime and dependency baseline

- Node.js 20 LTS, TypeScript, Zod, Vitest.
- `@langchain/langgraph` 1.4.8 and `@langchain/core` 1.2.3, pinned exactly.
- `@langchain/langgraph-checkpoint-redis` 1.0.10, pinned exactly. It requires
  RedisJSON and RediSearch, so Compose uses the pinned Redis 7 Stack server
  image `redis/redis-stack-server:7.4.0-v8` instead of module-free
  `redis:7-alpine`.
- BullMQ 5.80.6 and ioredis 5.11.1, pinned exactly.
- Zod 3.25.76 and zod-to-json-schema 3.25.2, pinned exactly across the shared
  contract package so LangGraph's peer constraint and Pydantic parity generation
  both remain supported.
- Python `redis` 8.0.1 for the FastAPI audit-stream consumer.

The version choices follow the official LangGraph installation/persistence
guides, the official Redis checkpoint package requirements, and BullMQ's
documented Redis queue/idempotency model.

## Cross-process contracts

`packages/contracts/src/worker.ts` is the wire-schema source of truth and
`backend/app/contracts/worker.py` is its Pydantic mirror. Both forbid unknown
fields and use bounded, pattern-validated identifiers.

The existing `WorkerJobEnvelope` remains schema version 1 and gains bounded ID,
timestamp, and payload constraints. The following version-1 contracts are added:

- `AgentNodeName`: `orchestrator`, `profile`, `path`, `resource`, `coach`,
  `assessment`.
- Six node input/output schemas. The orchestrator chooses one of the five
  specialist routes; tutoring is handled by `resource` as required by V1.0.
- `AgentProposalEnvelope`: run/event/trace identity, producing node, proposal
  kind, validated proposal body, completion status, and timestamp.
- `AgentAuditEnvelope`: monotonic sequence, run/event/trace identity, event type,
  node/tool/checkpoint metadata, safe detail, and timestamp.
- `AgentReplayRequest`: original event ID, checkpoint ID, and a new replay event
  ID. Replay never overwrites the original run.

Payloads contain IDs, bounded educational context, evidence summaries, proposal
data, safe error codes, and digests. They never contain credentials, raw system
prompts, unrestricted URLs, stack traces, or local paths.

## Six-node governance

Each node exports one immutable definition containing its input schema, output
schema, allowed tools, forbidden permissions, timeout, one schema-repair retry,
and deterministic fallback.

| Node | Responsibility | Allowed tool capabilities | Forbidden authority |
|---|---|---|---|
| orchestrator | Validate intent, choose one specialist, summarize | `llm.complete` | any formal-state write |
| profile | Explain evidence and propose profile changes | `evidence.read`, `llm.complete` | update formal profile |
| path | Propose main/remedial/review/resource needs | `profile.read`, `course.read`, `llm.complete` | publish path/task or bypass validator |
| resource | Propose five resource types and tutoring answer | `knowledge.search`, `llm.complete`, `image.generate` | modify profile/path or publish resource |
| coach | Explain failures and propose bounded hints/tests | `sandbox.evidence.read`, `llm.complete` | decide mastery or execute arbitrary code |
| assessment | Propose open-response/process feedback | `evidence.read`, `llm.complete` | write evidence/mastery directly |

All nodes additionally forbid direct database access, filesystem access, shell
execution, provider-secret access, unrestricted network access, and arbitrary
tool names. The tool registry checks the node allowlist before invocation,
validates input/output schemas, applies an AbortSignal deadline, and emits a
redacted audit event. User or provider text cannot dynamically name a privileged
capability, which makes prompt-injected tool requests data rather than commands.

The execution shell performs input validation, a bounded provider call, output
validation, one repair attempt for invalid output, then the node-specific
fallback. Timeouts, schema failures, forbidden tools, and provider failures use
stable error/fallback codes.

## LangGraph state and routing

The graph state contains the validated job, selected route, validated proposal,
safe audit events, and a terminal failure/fallback marker. The graph is explicit:

```text
START -> orchestrator -> exactly one of profile/path/resource/coach/assessment -> END
```

`WorkerJobKind` constrains the allowed route; the orchestrator may refine intent
within that set but cannot invent a node. LangGraph is compiled with a
`RedisSaver`. The `thread_id` is a SHA-256 digest of tenant and original event
identity, avoiding Redis key-pattern injection and preventing raw tenant IDs from
becoming checkpoint keys. Each super-step is checkpointed synchronously.

Replay loads a specific checkpoint under the original thread and invokes the
remaining graph with a new replay event identity. Earlier nodes are skipped by
LangGraph, later provider/tool operations re-run through the same idempotency and
policy gates, and both the original and replay chains remain auditable.

## Queue, duplicate handling, and events

BullMQ queue `pymentor:agent-jobs:v1` accepts only a parsed
`WorkerJobEnvelope`. Its job ID is a SHA-256 digest of `event_id`; this gives
queue-level deduplication without exposing unsafe job-ID characters. Jobs use
bounded attempts and exponential backoff only for retryable categories.

The processor also records a Redis run key. A completed duplicate returns the
cached validated proposal. A retry after interruption resumes the same LangGraph
thread from its latest checkpoint. Non-retryable schema/policy failures finish
once. Provider/tool effects receive a deterministic idempotency key composed of
event, node, tool, and call sequence.

Worker progress, proposal, and audit messages are appended to capped Redis stream
`pymentor:agent-events:v1`. Every message is a versioned JSON envelope. FastAPI
uses a consumer group, acknowledges only after its PostgreSQL transaction
commits, and treats duplicate stream IDs/event sequences idempotently.

## Durable audit and authority boundary

Migration `0006` adds normalized `agent_definitions`, `agent_runs`, and
`agent_tool_calls` tables. `agent_runs.event_id` is unique; tool calls are unique
per run and sequence. Runs store safe input/output snapshots, status, route,
checkpoint thread/latest checkpoint IDs, fallback/error code, timestamps, and
trace identity. Tool calls store capability name, status, argument/result
digests, latency, retry count, and safe error code—not raw prompts or secrets.

The FastAPI audit consumer validates each stream message with Pydantic, locks or
upserts the matching run, appends tool/checkpoint audit, and commits before
acknowledgement. It never accepts a Worker request to mutate learning-domain
tables. Replay lookup returns only the run/checkpoint metadata required to submit
a replay; the public admin route is deferred to BE-010.

## Error handling and shutdown

- Invalid job envelope: `VALIDATION_ERROR`, no retry, safe audit if identity can
  be recovered.
- Forbidden tool/permission: `FORBIDDEN_TOOL`, no retry, security audit.
- Provider timeout: abort call, use approved node fallback; retry the job only if
  no valid fallback exists.
- Transient Redis/provider failure: bounded exponential retry using the same
  event/thread/idempotency identities.
- Exhausted retry or invalid fallback: `FAILED_FINAL` with redacted details.
- Shutdown: stop accepting jobs, wait a bounded grace period, close BullMQ,
  checkpointer, Redis clients, and HTTP health server.

## Test and acceptance strategy

TDD slices cover:

1. Zod/Pydantic parity and golden payloads for every node and envelope.
2. Every node's allowlist, forbidden permissions, timeout, schema repair, and
   fallback; explicit prompt-injection and forbidden-tool attempts.
3. StateGraph node/edge identity and deterministic routing for all job kinds.
4. Duplicate BullMQ jobs, retry/final classification, cached completion, and
   restart/resume behavior.
5. Redis Stack integration: checkpoint creation, state history, replay from a
   chosen checkpoint, and capped event stream.
6. PostgreSQL migration round trip plus idempotent Agent/tool audit ingestion.
7. Full TypeScript typecheck/Vitest, Pydantic-Zod conformance, Ruff/mypy/pytest,
   Compose validation, and a real Redis/PostgreSQL worker smoke.

BE-006 is complete only when the six-node graph runs against the pinned Redis
service, duplicates do not repeat completed work, checkpoint replay is proven,
the audit rows are durable and redacted, and no path lets the Worker commit
formal learning state.
