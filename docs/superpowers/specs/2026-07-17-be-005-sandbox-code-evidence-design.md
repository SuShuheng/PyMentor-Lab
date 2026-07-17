# BE-005 Sandbox and Code Evidence Design

**Status:** Approved in conversation on 2026-07-17

## Goal

Run untrusted student Python behind a real Linux container boundary and turn the
bounded outcome into revision, test, hint, trace, and assessment evidence. The
system must distinguish student-caused failures from runner/platform failures so
infrastructure faults never reduce mastery or independence.

## Scope

BE-005 owns:

- the sandbox Supervisor and fixed Python runtime harness;
- per-run Linux container creation, hardening, cleanup, and result normalization;
- visible and hidden declarative test execution in separate containers;
- deterministic, bounded AST trace frames;
- append-only code revisions, run lifecycle/history, test results, and hint usage;
- student code-run, submission, result-query, and hint APIs;
- shared Pydantic/Zod contracts and the generated OpenAPI client;
- assessment evidence consumed by the BE-004 deterministic mastery API;
- unit, API, migration, protocol, and real-container security tests.

BE-005 does not own:

- arbitrary package installation, terminals, notebooks with host filesystem access,
  or outbound network access;
- Agent-generated hints or feedback (BE-006); BE-005 stores deterministic static
  hints and defines the future Agent proposal boundary;
- resource generation, object storage, or provider calls (BE-007);
- frontend editor, trace player, and diff presentation (FE-005);
- production orchestration beyond the documented dedicated/rootless Docker Engine
  requirement.

## Chosen Architecture

Use a dedicated Sandbox Supervisor that is the only component allowed to create
job containers. FastAPI validates the authenticated student command, loads the
private immutable task snapshot, persists a run reservation, and sends a signed,
canonical request to the Supervisor. The Supervisor starts a new hardened Linux
container for each visible or hidden phase and returns one bounded protocol result.

```text
Student API client
  -> FastAPI command boundary
  -> PostgreSQL QUEUED run + revision + audit + Outbox
  -> authenticated Sandbox Supervisor
  -> visible ephemeral container
  -> hidden ephemeral container (submission only)
  -> bounded result normalization
  -> PostgreSQL final state + tests + evidence + audit + Outbox
  -> generated API response
```

The host-subprocess executor is an explicitly insecure test adapter. It may exercise
pure protocol and policy logic in unit tests, but FastAPI must reject it outside a
test environment and its results cannot be accepted as formal submission evidence.

### Rejected alternatives

1. FastAPI directly controlling Docker is rejected because it puts Docker daemon
   authority in the Internet-facing process and expands the impact of request
   validation errors.
2. A long-lived sandbox container spawning child processes is rejected as the trusted
   boundary because files, process state, and leaks may survive between students.
3. AST/import restrictions without an OS container boundary are rejected because
   Python language restrictions are not a security sandbox.

## Trust Boundaries

### FastAPI

FastAPI owns authentication, tenant/student scope, task/revision/run persistence,
idempotency, private task-policy lookup, evidence decisions, audit, and Outbox. It
never accepts a client-supplied image, command, test, path, environment variable,
resource limit, or hidden-test identifier.

### Sandbox Supervisor

The Supervisor accepts only a strict signed `SandboxExecutionRequest`. It has no
database, Redis, object-store, provider, or JWT credential. It receives source,
declarative cases, and a normalized policy for one run; logs only request/run IDs,
trace ID, durations, status, and aggregate resource counts.

The API signs the canonical JSON body with HMAC-SHA256 using a dedicated service
secret. The Supervisor checks timestamp skew, nonce uniqueness, body digest, and
signature with constant-time comparison. The secret is never sent to a job container.

### Job container

The job container receives one canonical request through stdin. A trusted PID 1
harness captures the untrusted child through pipes and writes the only protocol frame
to container stdout after the child exits. Student file descriptors never reference
the Supervisor control stream or Docker socket.

Production must use a dedicated sandbox host or rootless Docker Engine. Local Docker
Desktop's Linux VM may be used for development/security smoke tests, but is not the
production isolation claim. A shared rootful daemon socket is not mounted into the
FastAPI container.

## Private Task Policy and Public Redaction

The immutable `TaskVersion.snapshot.tests_policy` becomes a validated object:

```json
{
  "entrypoint": {"kind": "FUNCTION", "name": "solve"},
  "allowed_imports": ["math", "statistics"],
  "visible": [
    {"id": "v-basic", "args": [[1, 2]], "kwargs": {}, "expected": 3,
     "comparison": "EQUAL", "transfer": false}
  ],
  "hidden": [
    {"id": "h-boundary", "args": [[0, 0]], "kwargs": {}, "expected": 0,
     "comparison": "EQUAL", "transfer": true}
  ]
}
```

`entrypoint.kind` is `FUNCTION` or `SCRIPT`. Function cases use JSON-serializable
`args`, `kwargs`, and `expected`. Script cases use bounded `stdin` and expected stdout.
Comparisons are `EQUAL`, `APPROX`, `UNORDERED`, or `MATCHES`. No case contains Python
source to execute.

`hint_policy` contains `max_level` from 0 through 3 and an ordered `hints` array with
`key`, `level`, `content`, and `independence_cost` from 0 through 100. Content is a
static server-owned snapshot in BE-005. Future Agent hints must enter as validated
proposals and cannot modify historical policy.

The start-task response must use a public projection. It includes prompt, entrypoint,
allowed imports, visible case IDs/examples, hint budget, mastery summary, and resource
versions. It excludes hidden cases, hidden IDs, expected hidden values, private policy
metadata, and any container configuration.

## Persistence Model

Migration `0005_sandbox_code_evidence` adds five normalized tables.

### `code_revisions`

- UUID primary key, tenant/student/task-instance foreign keys;
- positive `sequence`, nullable parent revision ID, source text, SHA-256 digest;
- source byte length check of 1 through 65,536;
- unique `(task_instance_id, sequence)` and `(task_instance_id, source_digest)`;
- append-only application service; an identical digest reuses the existing revision.

### `code_runs`

- UUID primary key plus unique, opaque `run_id` string;
- tenant/student/task-instance/revision foreign keys;
- required foreign key to the scoped idempotency reservation so recovery can complete
  the original command response;
- mode `RUN`, `TRACE`, or `SUBMIT`;
- formal status `QUEUED`, `RUNNING`, `COMPLETED`, `USER_ERROR`,
  `PLATFORM_ERROR`, `TIMEOUT`, or `CANCELLED`;
- immutable policy digest and bounded JSON policy snapshot;
- nullable bounded normalized result and trace-frame JSON;
- optimistic `version`, requested/started/completed/deadline timestamps;
- partial unique index allowing one `QUEUED` or `RUNNING` run per task instance.

### `code_run_status_history`

- tenant/run foreign keys, nullable from-status, required to-status, reason, trace ID,
  and UTC timestamp;
- appended for every formal run transition.

### `test_results`

- tenant/run foreign keys, positive ordinal, opaque case ID, `VISIBLE` or `HIDDEN`;
- pass flag, safe message, bounded stdout/stderr, non-negative duration;
- transfer-case flag and comparison kind;
- unique `(run_id, ordinal)` and `(run_id, visibility, case_id)`.

Hidden rows store the private case ID for server audit, but the student projection
replaces it with `hidden-1`, `hidden-2`, and so on and never returns expected inputs or
values.

### `hint_usages`

- tenant/student/task-instance and optional revision foreign keys;
- positive sequence, hint key, level 1 through 3, cost 0 through 100, content snapshot;
- source `STATIC` or `AGENT_PROPOSAL`; BE-005 creates only `STATIC` rows;
- unique `(task_instance_id, sequence)`.

The migration downgrades only these five tables in reverse dependency order. It does
not alter BE-003 evidence or BE-004 task/mastery rows.

## Shared Contracts

Existing `SandboxRunStatus` continues to describe the inner execution outcome:
`PASSED`, `FAILED`, `ERROR`, `TIMEOUT`, or `CANCELLED`. A separate `CodeRunStatus`
describes the persisted lifecycle and avoids breaking the bootstrap result boundary.

New or revised Pydantic/Zod models are:

- `CodeRunMode` and `CodeRunStatus`;
- `TestVisibility` and `SandboxComparison`;
- `CodeRunRequest(task_instance_id, source_code, mode, expected_task_version,
  trace_enabled)`;
- `CodeSubmissionRequest(task_instance_id, source_code, expected_task_version)`;
- `CodeRevisionView` without host paths or hidden policy;
- `SandboxResourceUsage(cpu_ms, wall_ms, peak_memory_kb, exit_code)`;
- `SandboxTestCaseResult` with visibility, safe display name, transfer flag, truncation
  flags, and bounded output;
- `TraceFrame(sequence, line, event, func_name, locals)`;
- `SandboxResult` with `trace_frames`, resource usage, truncation flags, user error, and
  platform error;
- `CodeRunView` with lifecycle/version/revision/result/evidence ID;
- `HintRequest(level, revision_id, expected_task_version)` and `HintUsageView`;
- internal `SandboxExecutionRequest`, `SandboxExecutionPolicy`, and
  `SandboxExecutionResponse` shared by API and Supervisor.

All models forbid extra fields. Source is capped at 65,536 UTF-8 bytes; stdout and
stderr at 32,768 bytes each; safe messages at 2,000 characters; test results at 256;
trace frames at 1,000; locals per frame at 32; local names at 128 characters; and
rendered local values at 512 characters.

## Student APIs

### `POST /api/v1/code/runs`

Requires authentication and `Idempotency-Key`. It loads an active student-owned task
instance, validates the optimistic version, creates/reuses a revision, executes only
visible cases, and returns a `CodeRunView`. `TRACE` additionally enables trace frames.

### `POST /api/v1/code/submissions`

Requires authentication and `Idempotency-Key`. It runs visible and hidden phases in
separate containers, persists both result sets, and emits deterministic assessment
evidence when the outcome is student-caused. It returns a `CodeRunView` with an
`evidence_event_id` suitable for the existing BE-004 task-submission command.

### `GET /api/v1/code/runs/{run_id}`

Returns only a run matching both tenant and authenticated student. Hidden results use
the redacted projection. Inaccessible IDs return the existing non-disclosing 404
envelope.

### `POST /api/v1/code/runs/{run_id}/cancel`

Requires authentication and `Idempotency-Key`. It row-locks a student-owned
non-terminal run, asks the Supervisor to kill/remove every container with that run
label, and then commits `CANCELLED`, history, audit, idempotency response, and Outbox.
Replaying cancellation returns the same terminal view. A terminal non-cancelled run
returns `CONFLICT` rather than rewriting history.

### `POST /api/v1/tasks/{task_instance_id}/hints`

Requires authentication and `Idempotency-Key`. The requested level must be the next
available level, within the immutable budget, and the revision/task versions must
match. The command stores one hint usage plus audit and Outbox atomically and returns
the static hint content. Replays return the original row.

All write routes preserve the BE-003 scoped idempotency, audit, trace, and Outbox
rules. No response exposes source code by default; revision source retrieval is a
separate future notebook query concern.

## Formal Run State Machine

Allowed transitions are:

```text
none -> QUEUED
QUEUED -> RUNNING | CANCELLED | PLATFORM_ERROR
RUNNING -> COMPLETED | USER_ERROR | PLATFORM_ERROR | TIMEOUT | CANCELLED
```

Terminal states never transition. Every transition increments `version`, appends
history, and emits an Outbox event in the same database transaction. The external
container execution is never performed while a database transaction is open.

Run creation commits revision, `QUEUED`, audit, idempotency reservation, and Outbox.
A second short transaction row-locks the run, moves it to `RUNNING`, appends history,
and commits the transition Outbox. Only then does the API invoke the Supervisor, with
no database transaction open. A third transaction records the terminal state,
persists normalized tests/result/evidence, completes the idempotency response, and
emits final audit/Outbox events. If the call fails, that transaction records
`PLATFORM_ERROR`.

A recovery service finds non-terminal rows whose deadline is in the past, takes a row
lock with skip-locked semantics, asks the Supervisor to remove the run label, marks
the row `PLATFORM_ERROR`, and completes the linked idempotency response. It is
replay-safe and never produces assessment evidence.

## Supervisor Protocol

The internal request contains only:

- protocol version, request/run/trace IDs, issued-at, nonce;
- source, entrypoint, selected declarative cases, allowed imports;
- fixed normalized policy and phase (`VISIBLE` or `HIDDEN`);
- trace enabled flag.

Canonical JSON is UTF-8, sorted-key, compact, and rejects NaN/infinity. The API sends
the body digest and HMAC signature in headers. Maximum body size is 512 KiB. The
Supervisor refuses stale timestamps, replayed nonces, invalid signatures, unknown
fields/versions, over-limit payloads, and unsupported policies before calling Docker.
There is one Supervisor instance per Docker Engine; it keeps a bounded nonce TTL cache
for that engine and treats an existing run label/request ID as an idempotent replay.

Its internal surface is fixed to signed `POST /internal/v1/executions` and signed
`DELETE /internal/v1/executions/{run_id}`. It exposes no generic Docker operation,
image, command, filesystem, or inspection endpoint.

The harness writes exactly one length-prefixed JSON response after a fixed magic
prefix. The Supervisor rejects missing, duplicate, malformed, oversized, or trailing
control frames as a platform protocol error. Student stdout/stderr are embedded only
as escaped bounded strings in that response.

## Container Hardening

Every job uses a pinned runtime image reference and fixed entrypoint with:

- Linux container platform and no published/exposed ports;
- `network=none`;
- read-only root filesystem and a size-limited `tmpfs` work directory;
- numeric non-root student child UID/GID;
- all Linux capabilities dropped and `no-new-privileges=true`;
- Docker's built-in seccomp profile, private PID/IPC/cgroup namespaces, and no device,
  secret, Docker socket, host bind, sibling-container, or service-network mount;
- one CPU, 128 MiB memory, no swap expansion, 32 PIDs, 16 MiB tmpfs, bounded file
  descriptors, file size, CPU time, and process count;
- disabled restart, fixed stop timeout, no health command, and `--rm`-equivalent
  cleanup enforced again in Supervisor `finally`;
- labels containing only run ID, protocol version, and expiry for recovery.

The Supervisor builds the Docker argument list from constants and validated numeric
policy values. It never concatenates a shell command. Image pulling during a student
request is disabled; missing images are platform errors. Cleanup failure is
security-logged and retried by recovery.

## Python Harness and Test Isolation

The harness launches Python with isolated mode, no site initialization, a minimal
environment, and a fresh work directory. It parses source with `ast`, rejects syntax
errors safely, and applies a policy visitor before execution.

Default allowed imports are `math`, `statistics`, `collections`, `itertools`,
`functools`, `decimal`, `fractions`, `re`, `string`, and `json`; a task may select a
subset. `os`, `sys`, `pathlib`, `socket`, `subprocess`, `multiprocessing`, `threading`,
`ctypes`, `importlib`, `inspect`, package-relative imports, star imports, and dynamic
import calls are denied. Dangerous builtins including `compile`, `eval`, `exec`,
`input`, `open`, `breakpoint`, and `__import__` are absent. File-I/O tasks are outside
V1; no `open` wrapper is exposed.

The AST policy is a pedagogical restriction, not the security boundary. The Linux
container remains authoritative even if Python introspection finds an unexpected
language path.

The trusted parent sends one declarative case at a time to an unprivileged child.
Hidden cases remain in parent memory and are never written into the student working
directory or returned over the child protocol. The child sees only the arguments for
the current call. Capabilities/seccomp prevent cross-process inspection. Visible and
hidden phases use separate containers and separate fresh filesystems.

Submissions always run the visible phase first. Failed comparisons and ordinary
student runtime errors still proceed to the hidden phase. Syntax/policy rejection,
student timeout/resource termination, cancellation, or any platform error skips the
hidden phase; skipped hidden tests are not reported as passed. A platform error in
either phase makes the entire submission a platform error and suppresses assessment
evidence because the formal hidden-test result is incomplete.

## Deterministic Trace Frames

AST instrumentation inserts calls before supported statements and on function
call/return/exception boundaries. A reserved prefix is generated by the harness;
student assignments, deletes, arguments, globals, or nonlocal declarations using the
prefix are rejected. The callback reference is installed by the harness after module
globals are created.

Frames contain a sequence, positive source line, `call`, `line`, `return`, or
`exception`, a bounded function name, and sanitized locals. Locals exclude reserved
names, dunder names, modules, functions, classes, file handles, frames, tracebacks,
and values whose type is not on the scalar/list/tuple/dict allowlist. Dict keys are
sorted, object addresses are replaced, cycles are marked, and length/depth are capped.

The same source, cases, policy, and Python runtime digest must produce the same frame
sequence. Time, randomness, network, concurrency, and process creation are unavailable.
Exceeding the frame budget truncates trace output without failing otherwise valid
student code. Removing or replacing the reserved callback is a student policy error.

## Hints and Assessment Evidence

Hint levels are monotonic. A student cannot request level 3 before levels 1 and 2,
exceed `max_level`, attach a hint to another student's revision, or replay a hint
against a changed task version. Hint use never changes a profile directly.

For `SUBMIT`, a student-caused terminal outcome emits one append-only
`ASSESSMENT_RECORDED` evidence event scoped to the task, course, and node:

- `correct`: all visible and hidden cases passed;
- `hidden_tests_passed`: all hidden cases passed and at least one hidden case exists;
- `hints_used`: number of hint usage rows for the task instance;
- `support_level`: maximum used hint level, or zero;
- `independence_score`: `max(0, 1 - total_independence_cost / 100)`;
- `transfer_score`: passed transfer hidden cases divided by total transfer hidden cases;
  if no transfer case exists, one when all hidden tests pass and zero otherwise;
- `platform_error`: false;
- run/revision/policy/runtime digests for audit, with no source or hidden case values.

Syntax errors, runtime errors, failed tests, denied operations, and student-triggered
resource limits may create this evidence. `PLATFORM_ERROR` and infrastructure-caused
`CANCELLED` never create assessment evidence. A separate platform-failure audit and
Outbox event supports operations without affecting BE-004 mastery.

## Error Classification

Student errors include syntax/runtime errors, failed comparisons, denied imports or
builtins, traversal attempts, network/subprocess/dynamic-import attempts,
instrumentation tamper, and student-triggered CPU/memory/PID/file/output limits. They
map to `SANDBOX_USER_ERROR` or `TIMEOUT` with safe bounded details.

Platform errors include unavailable Docker Engine, missing/pull-required image,
container-create/start/inspect failure, invalid Supervisor/harness protocol, Supervisor
timeout not attributable to the child, result persistence failure, and cleanup
failure. They map to `SANDBOX_PLATFORM_ERROR`, are retryable when safe, and never
become negative learning evidence.

Cancellation is idempotent. A cancellation before `RUNNING` produces no result;
cancellation during execution kills and removes labeled containers before finalizing.
Unexpected exceptions use the existing redacted `INTERNAL_ERROR` envelope with only
trace references.

## Logging and Data Safety

Source, test inputs/expected values, hidden IDs, hint content, captured output,
locals, HMAC bodies/signatures, image registry credentials, host paths, and Docker
socket details are forbidden in structured logs, audit details, and Outbox payloads.
Allowed telemetry is run/trace/task IDs, tenant ID, status, phase, duration, counts,
bounded resource numbers, policy/runtime digests, and stable error categories.

Database source and bounded results are student records governed by existing tenant
scope. API responses never reveal absolute machine paths. Error normalization strips
container IDs, image registry names beyond an allowlisted logical runtime name,
tracebacks, memory addresses, and control characters.

## Testing Strategy

### Pure policy and protocol tests

- Pydantic/Zod conformance, JSON bounds, lifecycle transitions, canonical signature,
  timestamp/nonce replay, result framing, truncation, and error normalization;
- AST import/builtin/attribute/reserved-name rules and deterministic trace sanitation;
- visible/hidden projection and deterministic assessment facts;
- fake-executor platform failure and stale-run recovery.

### Persistence and API tests

- migration upgrade/downgrade, constraints, partial active-run index, and append-only
  revision reuse;
- tenant/student/task scope, optimistic conflict, idempotent replay, concurrent active
  run conflict, hint order/budget, hidden redaction, audit, Outbox, and stable errors;
- code submission to accepted BE-003 evidence to BE-004 mastery consumption;
- platform error produces no assessment evidence and preserves mastery.

### Real-container security tests

Using the pinned runtime image and the actual Linux Docker Engine, verify:

- infinite loop timeout and cleanup;
- fork/process-bomb denial and PID bound;
- memory and file-size exhaustion;
- stdout/stderr/control-frame flooding;
- filesystem traversal and host-sensitive path denial;
- no network, DNS, raw socket, subprocess, dynamic import, or package installation;
- no Docker socket, devices, capabilities, writable root, or host bind mounts;
- result-frame spoof attempts cannot become trusted protocol output;
- instrumentation tamper is detected;
- visible and hidden phases use distinct containers and hidden policy is absent from
  the student filesystem/API response;
- container removal after pass, failure, timeout, cancellation, and malformed output;
- a later valid run succeeds after every failure class.

Security integration tests skip only when the Docker daemon is unavailable and report
the skip reason. BE-005 cannot be marked complete without a dated successful run on a
Linux Docker Engine with seccomp and cgroups enabled.

## Deployment and Configuration

The runtime and Supervisor use separate images. The runtime image contains only the
fixed harness and Python standard library; it has no Docker client or service secret.
The Supervisor image contains the service and Docker client but no application
database/provider credentials. Compose places the Supervisor on an internal-only
network with FastAPI and exposes no host port.

Configuration names are fixed and validated at startup: logical runtime image,
Supervisor URL, shared-secret reference, request/body/time limits, and whether the
current environment is `test`, `development`, or `production`. Production startup
fails if the insecure host executor is selected or the runtime image is unpinned.

## Rollback and Compatibility

The five BE-005 tables are additive. Existing BE-004 tasks remain readable; code-run
commands require a validated new tests/hint policy and reject legacy placeholder
snapshots with `VALIDATION_ERROR` rather than guessing. The public task projection is
an intentional security tightening of the bootstrap generic snapshot.

Application rollback leaves BE-005 rows unused. Data rollback uses the tested 0005
downgrade only after preserving student code records according to the deployment
backup procedure; no ad-hoc destructive SQL is used.

## Security References

- Docker Engine security and daemon attack surface:
  <https://docs.docker.com/engine/security/>
- Docker rootless mode:
  <https://docs.docker.com/engine/security/rootless/>
- Docker built-in seccomp profile:
  <https://docs.docker.com/engine/security/seccomp/>
- Docker container run resource and isolation flags:
  <https://docs.docker.com/reference/cli/docker/container/run>
- Docker Compose service isolation fields:
  <https://docs.docker.com/reference/compose-file/services/>
