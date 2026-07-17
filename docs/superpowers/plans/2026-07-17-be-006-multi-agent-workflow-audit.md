# BE-006 Multi-Agent Workflow and Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a six-node LangGraph.js Worker that consumes versioned Redis
jobs idempotently, persists native checkpoints, emits replayable/redacted audit
events, and leaves every formal learning-state mutation to FastAPI.

**Architecture:** A shared Zod/Pydantic wire boundary feeds immutable node
definitions and a policy-enforcing executor. An explicit LangGraph StateGraph
routes through the orchestrator to exactly one specialist. BullMQ provides the
at-least-once queue, RedisSaver provides super-step checkpoints, and a capped
Redis stream feeds a FastAPI consumer that owns PostgreSQL Agent audit tables.

**Tech Stack:** Node.js 20, TypeScript, LangGraph.js 1.4.8, BullMQ 5.80.6,
Redis Stack 7.4, Zod 3.25, Vitest, Python 3.13, FastAPI, Pydantic, SQLAlchemy,
Alembic, redis-py, PostgreSQL 16, Docker Compose.

## Global Constraints

- Work only on the backend-owned paths declared by BE-006.
- Six nodes are exactly `orchestrator`, `profile`, `path`, `resource`, `coach`,
  and `assessment`; tutoring routes to `resource`.
- Worker output is proposal/progress/audit only. Worker code must not mutate
  profiles, paths, tasks, evidence, mastery, reviews, or published resources.
- Every node has an independent input schema, output schema, tool allowlist,
  forbidden permissions, timeout, one schema-repair retry, and fallback.
- No credentials, raw system prompts, stack traces, unrestricted URLs, or local
  paths may appear in Redis events or PostgreSQL audit snapshots.
- Queue delivery is at least once; event IDs, tool-call identities, checkpoint
  threads, and audit sequences make all processing replay-safe and idempotent.
- Every production behavior follows Red-Green-Refactor and each task ends with a
  focused test gate and one Conventional Commit.

---

### Task 1: Versioned Worker Contracts and Dependency Baseline

**Files:**
- Modify: `packages/contracts/package.json`
- Modify: `packages/contracts/src/worker.ts`
- Modify: `packages/contracts/src/contracts.test.ts`
- Modify: `packages/contracts/src/conformance.ts`
- Modify: `backend/app/contracts/worker.py`
- Modify: `backend/app/contracts/__init__.py`
- Modify: `backend/tests/test_contracts_parity.py`
- Modify: `workers/agent-worker/package.json`
- Modify: `pnpm-lock.yaml`

**Interfaces:**
- Consumes: existing `WorkerJobKind`, `WorkerJobStatus`, and
  `WorkerJobEnvelope` version 1.
- Produces: `AgentNodeName`, six node input/output schemas,
  `AgentProposalEnvelope`, `AgentAuditEnvelope`, `AgentReplayRequest`, and exact
  Pydantic mirrors exported by both contract packages.

- [ ] **Step 1: Write golden and rejection tests before schema changes**

Add table-driven Zod tests that parse one golden input/output for every node and
reject unknown fields, overlong IDs, invalid timestamps, unsupported proposal
kinds, unsafe audit detail keys, and a replay that reuses the original event ID.
Add matching Pydantic parity cases to `VALID_CASES` and `INVALID_CASES` in
`backend/tests/test_contracts_parity.py`.

```typescript
it.each(agentContractGoldens)("parses $name", ({ schema, value }) => {
  expect(schema.parse(value)).toEqual(value);
});

it("rejects replay identity reuse", () => {
  expect(() =>
    AgentReplayRequest.parse({
      schema_version: 1,
      original_event_id: "evt_original",
      replay_event_id: "evt_original",
      checkpoint_id: "chk_1",
    }),
  ).toThrow();
});
```

- [ ] **Step 2: Run the contract tests and capture the expected Red**

Run: `pnpm --filter @pymentor/contracts test`

Expected: FAIL because the new Agent schemas are not exported.

- [ ] **Step 3: Implement bounded Zod schemas and Pydantic mirrors**

Use `z.object(...).strict()`, maximum lengths, ISO datetime validation, and an
allowlist validator for audit-detail keys. Define proposal bodies as a
discriminated union rather than an unbounded record. Mirror every field and
validator in `backend/app/contracts/worker.py` with `extra="forbid"`.

- [ ] **Step 4: Pin compatible dependencies**

Run:

```powershell
pnpm --filter @pymentor/contracts add zod@3.25.76 zod-to-json-schema@3.25.2 --save-exact
pnpm --filter @pymentor/agent-worker add @langchain/langgraph@1.4.8 @langchain/core@1.2.3 @langchain/langgraph-checkpoint-redis@1.0.10 bullmq@5.80.6 ioredis@5.11.1 --save-exact
```

- [ ] **Step 5: Verify Green and cross-language parity**

Run:

```powershell
pnpm --filter @pymentor/contracts test
pnpm contracts:check
uv run --no-cache pytest -p no:cacheprovider backend/tests/test_contracts_parity.py -q
pnpm typecheck
```

Expected: all commands exit 0; JSON Schema generation reports no Pydantic-Zod
drift.

- [ ] **Step 6: Commit Task 1**

```powershell
git add packages/contracts backend/app/contracts backend/tests/test_contracts_parity.py workers/agent-worker/package.json pnpm-lock.yaml
git commit -m "feat(contracts): define BE-006 agent workflow envelopes"
```

---

### Task 2: Independent Node Policies and Policy-Enforcing Executor

**Files:**
- Create: `workers/agent-worker/src/agents/types.ts`
- Create: `workers/agent-worker/src/agents/policies.ts`
- Create: `workers/agent-worker/src/agents/tool-registry.ts`
- Create: `workers/agent-worker/src/agents/executor.ts`
- Create: `workers/agent-worker/src/agents/nodes.ts`
- Create: `workers/agent-worker/src/agents/executor.test.ts`

**Interfaces:**
- Consumes: the six shared node input/output schemas from Task 1.
- Produces: `AgentNodeDefinition`, `ToolRegistry`, `AgentProviderPort`,
  `executeNode(definition, input, context)`, and `agentNodes` keyed by all six
  `AgentNodeName` values.

- [ ] **Step 1: Write one focused Red test per policy behavior**

Tests must assert exact allowlists/forbidden permissions for all six nodes,
input rejection before provider invocation, forbidden-tool rejection, malicious
prompt text remaining inert, abort on timeout, one repair attempt after invalid
provider output, fallback after the repair fails, and redacted audit output.

```typescript
it("rejects a tool that the active node does not allow", async () => {
  const registry = new ToolRegistry({ "formal_state.write": forbiddenTool });
  await expect(
    registry.invoke(profileDefinition, "formal_state.write", {}, context),
  ).rejects.toMatchObject({ code: "FORBIDDEN_TOOL" });
  expect(forbiddenTool.calls).toBe(0);
});
```

- [ ] **Step 2: Run executor tests and verify Red**

Run: `pnpm --filter @pymentor/agent-worker test -- src/agents/executor.test.ts`

Expected: FAIL because node definitions and executor do not exist.

- [ ] **Step 3: Implement immutable definitions and the minimal executor**

`AgentNodeDefinition` contains `name`, `inputSchema`, `outputSchema`,
`allowedTools`, `forbiddenPermissions`, `timeoutMs`, and `fallback`. The executor
creates an `AbortController`, validates input, performs one provider attempt plus
one repair attempt, validates output, and invokes the node fallback if both
outputs are invalid or the provider times out. It records only safe sizes,
digests, status, latency, and stable codes.

- [ ] **Step 4: Implement the tool registry as the only capability gateway**

Each tool has Zod input/output schemas and an `invoke(input, signal,
idempotencyKey)` method. The registry checks the node allowlist before lookup,
derives `sha256(eventId|node|tool|sequence)`, validates both sides, applies the
same deadline, and emits `TOOL_STARTED` plus `TOOL_COMPLETED` or `TOOL_FAILED`.

- [ ] **Step 5: Run focused and Worker tests**

Run:

```powershell
pnpm --filter @pymentor/agent-worker test -- src/agents/executor.test.ts
pnpm --filter @pymentor/agent-worker typecheck
```

Expected: all policy, timeout, repair, fallback, prompt-injection, and redaction
tests pass with no TypeScript errors.

- [ ] **Step 6: Commit Task 2**

```powershell
git add workers/agent-worker/src/agents
git commit -m "feat(worker): enforce six independent agent policies"
```

---

### Task 3: Explicit LangGraph StateGraph and Deterministic Routing

**Files:**
- Create: `workers/agent-worker/src/workflow/state.ts`
- Create: `workers/agent-worker/src/workflow/graph.ts`
- Create: `workers/agent-worker/src/workflow/graph.test.ts`
- Modify: `workers/agent-worker/src/index.ts`

**Interfaces:**
- Consumes: `agentNodes`, `executeNode`, shared job/proposal contracts, and a
  `BaseCheckpointSaver` supplied by the caller.
- Produces: `buildAgentGraph(dependencies)` and
  `invokeAgentGraph(job, { threadId, checkpointId? })`.

- [ ] **Step 1: Write graph topology and route Red tests**

Assert that the drawable graph contains exactly six business nodes plus
START/END; every job kind executes `orchestrator` then exactly one specialist;
`tutoring_answer` routes to `resource`; an orchestrator result outside the
kind's allowed route fails closed; and the output parses as
`AgentProposalEnvelope`.

```typescript
it.each([
  ["profile_diagnose", "profile"],
  ["path_recommend", "path"],
  ["resource_generate", "resource"],
  ["tutoring_answer", "resource"],
  ["coding_coach", "coach"],
  ["assessment_feedback", "assessment"],
] as const)("routes %s through orchestrator to %s", async (kind, route) => {
  const result = await harness.invoke(jobFor(kind));
  expect(result.executedNodes).toEqual(["orchestrator", route]);
});
```

- [ ] **Step 2: Run graph tests and verify Red**

Run: `pnpm --filter @pymentor/agent-worker test -- src/workflow/graph.test.ts`

Expected: FAIL because the graph factory does not exist.

- [ ] **Step 3: Implement graph state and six-node topology**

Define a typed StateGraph state with validated job, route, executed-node list,
proposal, audit sequence, and terminal failure/fallback. Add START to
orchestrator, conditional edges to the five specialists, and each specialist to
END. Do not add generic node loops or free-form Agent chat.

- [ ] **Step 4: Verify Green and graph checkpoint compatibility**

Run:

```powershell
pnpm --filter @pymentor/agent-worker test -- src/workflow/graph.test.ts
pnpm --filter @pymentor/agent-worker typecheck
```

Expected: topology and all six routing cases pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add workers/agent-worker/src/workflow workers/agent-worker/src/index.ts
git commit -m "feat(worker): route six agents with LangGraph"
```

---

### Task 4: BullMQ Queue, Idempotent Processor, and Versioned Event Stream

**Files:**
- Create: `workers/agent-worker/src/queue/identities.ts`
- Create: `workers/agent-worker/src/queue/events.ts`
- Create: `workers/agent-worker/src/queue/processor.ts`
- Create: `workers/agent-worker/src/queue/runtime.ts`
- Create: `workers/agent-worker/src/queue/processor.test.ts`
- Modify: `workers/agent-worker/src/index.ts`

**Interfaces:**
- Consumes: `WorkerJobEnvelope`, `AgentAuditEnvelope`, `AgentProposalEnvelope`,
  and `invokeAgentGraph`.
- Produces: `createAgentQueue`, `createAgentWorker`, `processAgentJob`,
  `publishAgentEvent`, `jobIdForEvent`, and bounded shutdown methods.

- [ ] **Step 1: Write Red tests with an in-memory Redis port**

Test invalid envelope rejection before graph invocation, SHA-256 job identity,
completed duplicate returning the cached proposal, interrupted duplicate
resuming the same thread, retryable versus final error classification,
monotonic audit sequence, capped stream writes, and deterministic tool
idempotency identities.

- [ ] **Step 2: Run processor tests and verify Red**

Run: `pnpm --filter @pymentor/agent-worker test -- src/queue/processor.test.ts`

Expected: FAIL because queue runtime modules do not exist.

- [ ] **Step 3: Implement the transport-independent processor**

Parse the job before any Redis/provider operation. Use `SET key value NX` for
the run claim, a completion record containing only the validated proposal, and
the same thread ID on retries. Emit `RUN_STARTED`, node/tool events,
`CHECKPOINT_SAVED`, and one terminal event with monotonically increasing
sequence numbers.

- [ ] **Step 4: Implement BullMQ and Redis stream adapters**

Use queue `pymentor:agent-jobs:v1`, event stream
`pymentor:agent-events:v1`, bounded attempts, exponential backoff, and capped
completed/failed retention. Use `XADD MAXLEN ~ 10000` for events. BullMQ job
data remains the full versioned envelope while the custom job ID is its digest.

- [ ] **Step 5: Verify Green**

Run:

```powershell
pnpm --filter @pymentor/agent-worker test -- src/queue/processor.test.ts
pnpm --filter @pymentor/agent-worker typecheck
```

Expected: duplicate, retry, final-failure, event-order, and stream-bound tests
pass.

- [ ] **Step 6: Commit Task 4**

```powershell
git add workers/agent-worker/src/queue workers/agent-worker/src/index.ts
git commit -m "feat(worker): process versioned Redis jobs idempotently"
```

---

### Task 5: RedisSaver Checkpoints and Replay Against Redis Stack

**Files:**
- Create: `workers/agent-worker/src/workflow/checkpoints.ts`
- Create: `workers/agent-worker/src/workflow/replay.ts`
- Create: `workers/agent-worker/src/workflow/checkpoints.integration.test.ts`
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `buildAgentGraph`, `AgentReplayRequest`, and a Redis URL.
- Produces: `createCheckpointSaver`, `threadIdForJob`,
  `getCheckpointHistory`, and `replayFromCheckpoint`.

- [ ] **Step 1: Write skip-gated real Redis Red tests**

The integration test requires `PYMENTOR_REDIS_URL`. It invokes a two-node run,
asserts a checkpoint at every super-step, selects the checkpoint before the
specialist, replays with a new event ID, proves the orchestrator is not
re-executed, and proves original history remains unchanged. Add an unsafe ID
case containing `*?[\\]` and assert the derived thread ID is a safe fixed-length
digest.

- [ ] **Step 2: Start the pinned Redis service and verify Red**

Run:

```powershell
docker compose up -d redis
$env:PYMENTOR_REDIS_URL='redis://127.0.0.1:6379/0'
pnpm --filter @pymentor/agent-worker test -- src/workflow/checkpoints.integration.test.ts
```

Expected: FAIL because RedisSaver setup and replay functions do not exist.

- [ ] **Step 3: Pin Redis Stack and implement saver lifecycle**

Change Compose to `redis/redis-stack-server:7.4.0-v8`, preserve AOF and the
existing volume/health contract, create `RedisSaver.fromUrl`, run its `setup()`
once at startup, compile the graph with synchronous durability, and close the
underlying client at shutdown.

- [ ] **Step 4: Implement safe replay**

Derive the original thread from tenant plus original event identity, load and
validate the requested checkpoint, invoke from that checkpoint with a new replay
event identity, and publish an audit link between original and replay runs.

- [ ] **Step 5: Verify real Redis Green and Compose validity**

Run:

```powershell
pnpm --filter @pymentor/agent-worker test -- src/workflow/checkpoints.integration.test.ts
docker compose config --quiet
docker compose exec -T redis redis-cli MODULE LIST
```

Expected: replay tests pass; Compose exits 0; RedisJSON and Search modules are
listed.

- [ ] **Step 6: Commit Task 5**

```powershell
git add workers/agent-worker/src/workflow docker-compose.yml .env.example
git commit -m "feat(worker): persist and replay LangGraph checkpoints"
```

---

### Task 6: PostgreSQL Agent Audit Models and Migration

**Files:**
- Create: `backend/app/models/agent.py`
- Create: `backend/migrations/versions/0006_agent_audit.py`
- Create: `backend/app/agent_audit.py`
- Create: `backend/tests/test_agent_audit.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: parsed Pydantic `AgentAuditEnvelope` and
  `AgentProposalEnvelope` instances.
- Produces: `AgentDefinition`, `AgentRun`, `AgentToolCall`,
  `ingest_agent_audit(db, event)`, `ingest_agent_proposal(db, proposal)`, and
  `get_agent_replay_metadata(db, event_id)`.

- [ ] **Step 1: Write model, migration, and ingestion Red tests**

Test that migration 0006 creates all three tables and round-trips; event ID is
unique; `(agent_run_id, sequence)` is unique for tool calls; duplicate audit
messages do not create rows; terminal proposals update rather than replace the
run; out-of-order terminal events retain monotonic status; and persisted JSON
contains no forbidden detail keys.

- [ ] **Step 2: Run focused tests and verify Red**

Run:

```powershell
$env:PYMENTOR_DATABASE_URL='postgresql+psycopg://pymentor:pymentor_dev@127.0.0.1:5432/pymentor?connect_timeout=5'
uv run --no-cache pytest -p no:cacheprovider backend/tests/test_agent_audit.py backend/tests/test_migrations.py -q
```

Expected: FAIL because migration 0006 and Agent models do not exist.

- [ ] **Step 3: Implement normalized models and reversible migration**

Use UUID primary/foreign keys, tenant/student/run indexes, named unique/check
constraints, timezone-aware timestamps, bounded strings, and JSONB only for
safe input/output snapshots. `AgentRun.event_id` is unique and every tool call
has a unique run/sequence pair.

- [ ] **Step 4: Implement idempotent ingestion**

Use row locks where a run already exists. Create run/tool rows from audit
events, update terminal status only through valid transitions, save checkpoint
metadata on the run, and reject any detail key outside the contract allowlist.
No function imports or modifies a learning-domain model.

- [ ] **Step 5: Verify Green, Ruff, and mypy**

Run:

```powershell
uv run --no-cache pytest -p no:cacheprovider backend/tests/test_agent_audit.py backend/tests/test_migrations.py -q
uv run --no-cache ruff check backend/app/models/agent.py backend/app/agent_audit.py backend/tests/test_agent_audit.py
uv run --no-cache ruff format --check backend/app/models/agent.py backend/app/agent_audit.py backend/tests/test_agent_audit.py
uv run --no-cache mypy backend/app/models/agent.py backend/app/agent_audit.py
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit Task 6**

```powershell
git add backend/app/models/agent.py backend/app/models/__init__.py backend/app/agent_audit.py backend/migrations/versions/0006_agent_audit.py backend/tests/test_agent_audit.py backend/tests/test_migrations.py
git commit -m "feat(backend): persist replayable agent audit"
```

---

### Task 7: FastAPI-Owned Redis Audit Consumer

**Files:**
- Create: `backend/app/agent_event_consumer.py`
- Create: `backend/tests/test_agent_event_consumer.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.env.example`
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: Redis stream `pymentor:agent-events:v1`, a SQLAlchemy session
  factory, and Task 6 ingestion functions.
- Produces: `consume_agent_events_once`, `run_agent_event_consumer`, and a
  lifespan-managed consumer enabled only by explicit configuration.

- [ ] **Step 1: Write stream-consumer Red tests**

Use a fake async Redis stream port and real PostgreSQL session. Assert schema
validation before DB writes, commit before XACK, no XACK after rollback,
duplicate delivery idempotency, consumer-group recovery of pending messages,
bounded shutdown, and disabled-by-default test startup.

- [ ] **Step 2: Run focused tests and verify Red**

Run: `uv run --no-cache pytest -p no:cacheprovider backend/tests/test_agent_event_consumer.py -q`

Expected: FAIL because the consumer module is absent.

- [ ] **Step 3: Add redis-py and explicit settings**

Run: `uv add 'redis==8.0.1'`

Add Redis URL, stream/group/consumer names, block timeout, batch size, and
`PYMENTOR_AGENT_EVENT_CONSUMER_ENABLED`. Tests default it to false; Compose sets
it true for the API service.

- [ ] **Step 4: Implement validation, transaction, acknowledgement, and shutdown**

Create the consumer group idempotently, read with `XREADGROUP`, parse the event
discriminant into its Pydantic envelope, open one DB transaction per message,
call the Task 6 ingestion service, commit, then XACK. On cancellation, finish the
current transaction and close Redis without swallowing `CancelledError`.

- [ ] **Step 5: Verify Green and application lifecycle**

Run:

```powershell
uv run --no-cache pytest -p no:cacheprovider backend/tests/test_agent_event_consumer.py backend/tests/test_agent_audit.py -q
uv run --no-cache ruff check backend/app/agent_event_consumer.py backend/app/main.py backend/app/config.py
uv run --no-cache mypy backend/app/agent_event_consumer.py backend/app/main.py backend/app/config.py
docker compose config --quiet
```

Expected: all commands exit 0; no background consumer starts in tests unless
explicitly enabled.

- [ ] **Step 6: Commit Task 7**

```powershell
git add backend/app/agent_event_consumer.py backend/tests/test_agent_event_consumer.py backend/app/config.py backend/app/main.py pyproject.toml uv.lock .env.example docker-compose.yml
git commit -m "feat(backend): consume agent audit events transactionally"
```

---

### Task 8: Production Worker Runtime, Health, and Graceful Shutdown

**Files:**
- Create: `workers/agent-worker/src/runtime/config.ts`
- Create: `workers/agent-worker/src/runtime/application.ts`
- Create: `workers/agent-worker/src/runtime/application.test.ts`
- Modify: `workers/agent-worker/src/health.ts`
- Modify: `workers/agent-worker/src/health.test.ts`
- Modify: `workers/agent-worker/src/server.ts`
- Modify: `infra/worker.Dockerfile`

**Interfaces:**
- Consumes: Redis URL, graph/checkpointer factory, queue runtime, and health app.
- Produces: `buildWorkerApplication`, `startWorkerApplication`, readiness state,
  and idempotent `close()`.

- [ ] **Step 1: Write runtime Red tests**

Assert fail-fast invalid/missing production Redis URL, health remains live while
readiness is false, readiness becomes true only after Redis/checkpointer/queue
startup, shutdown stops intake before closing dependencies, a second shutdown is
safe, and SIGTERM uses the bounded close path.

- [ ] **Step 2: Run runtime tests and verify Red**

Run: `pnpm --filter @pymentor/agent-worker test -- src/runtime/application.test.ts src/health.test.ts`

Expected: FAIL because the Worker application lifecycle does not exist.

- [ ] **Step 3: Implement the composed application**

Validate configuration, create one owned Redis/checkpointer/queue dependency
graph, start the health server, expose `/health` and `/ready`, and register
SIGINT/SIGTERM handlers. The close sequence pauses the BullMQ worker, waits the
configured grace period, closes worker/queue/checkpointer/Redis, then stops HTTP.

- [ ] **Step 4: Verify Green, typecheck, and image build**

Run:

```powershell
pnpm --filter @pymentor/agent-worker test -- src/runtime/application.test.ts src/health.test.ts
pnpm --filter @pymentor/agent-worker typecheck
docker build -f infra/worker.Dockerfile -t pymentor/agent-worker:be006 .
```

Expected: tests and typecheck pass; image build exits 0.

- [ ] **Step 5: Commit Task 8**

```powershell
git add workers/agent-worker/src/runtime workers/agent-worker/src/health.ts workers/agent-worker/src/health.test.ts workers/agent-worker/src/server.ts infra/worker.Dockerfile
git commit -m "feat(worker): run the checkpointed agent service"
```

---

### Task 9: Real Redis/PostgreSQL Acceptance and BE-006 Closure

**Files:**
- Create: `workers/agent-worker/src/acceptance/workflow.integration.test.ts`
- Modify: `docs/superpowers/plans/2026-07-17-be-006-multi-agent-workflow-audit.md`
- Modify outside code repository: `../.making/pymentor-lab/work-items/backend/BE-006/TASK.md`
- Modify outside code repository: `../.making/pymentor-lab/work-items/backend/BE-008/TASK.md`
- Modify outside code repository: `../.making/pymentor-lab/workstreams/backend/2026-07-17-pymentor-lab-v1/TRACK.md`

**Interfaces:**
- Consumes: the complete Worker, Redis Stack, FastAPI audit consumer, and
  PostgreSQL audit tables.
- Produces: dated, command-level BE-006 evidence and a clean handoff to BE-008.

- [ ] **Step 1: Write end-to-end Red acceptance**

Submit one golden job for each Worker kind plus invalid-schema,
forbidden-tool/prompt-injection, provider-timeout, duplicate, retry, checkpoint,
and replay cases. Assert six validated terminal proposals, no duplicated run or
tool audit rows, checkpoint history and replay linkage, redacted persistence,
and zero writes to formal learning tables.

- [ ] **Step 2: Rebuild/start exact services and verify the acceptance Red**

Run:

```powershell
docker compose up -d --build postgres redis api worker
$env:PYMENTOR_REDIS_URL='redis://127.0.0.1:6379/0'
$env:PYMENTOR_DATABASE_URL='postgresql+psycopg://pymentor:pymentor_dev@127.0.0.1:5432/pymentor?connect_timeout=5'
pnpm --filter @pymentor/agent-worker test -- src/acceptance/workflow.integration.test.ts
```

Expected before the final wiring correction: at least one focused assertion
fails for the missing or incorrect integration behavior; fix production code,
not the assertion, until Green.

- [ ] **Step 3: Run the complete verification matrix**

Run:

```powershell
pnpm lint
pnpm test
pnpm typecheck
pnpm contracts:check
uv run --no-cache ruff check backend sandbox
uv run --no-cache ruff format --check backend/app backend/tests sandbox
uv run --no-cache mypy backend/app workers/agent-worker 2>$null
uv run --no-cache pytest -p no:cacheprovider backend/tests sandbox/tests -m "not docker"
docker compose config --quiet
docker compose ps
git diff --check
```

Run mypy only on Python paths if the mixed-language path is rejected by mypy;
record the exact corrected command. Expected: every applicable gate exits 0,
with only intentional, documented skip markers.

- [ ] **Step 4: Request independent review and resolve all Critical/Important findings**

The reviewer checks contract parity, six distinct authorities, prompt/tool
isolation, timeout/fallback behavior, queue idempotency, checkpoint/replay,
Redis/PostgreSQL failure handling, audit redaction, and formal-state ownership.
Every accepted finding receives a regression test before its fix.

- [ ] **Step 5: Commit acceptance evidence code**

```powershell
git add workers/agent-worker/src/acceptance docs/superpowers/plans/2026-07-17-be-006-multi-agent-workflow-audit.md
git commit -m "test(worker): verify BE-006 replayable workflow"
```

- [ ] **Step 6: Close durable task records**

Move BE-006 through `IN_REVIEW` to `DONE`, record commits, commands, platform,
material results, reviewer identity/findings, and remaining risk. Set BE-008 to
`READY`, update `current_task`, and commit only those sidecar records.
