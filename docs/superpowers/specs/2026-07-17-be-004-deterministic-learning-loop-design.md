# BE-004 Deterministic Learning Loop Design

Status: approved by the frozen PyMentor Lab V1.0 design, the user-approved
backend contract, and the explicit instruction to continue all remaining
backend tasks.

## Goal

Implement the loop-boundary vertical slice from append-only evidence through
profile projection, validated learning paths, immutable task snapshots,
assessment, mastery decisions, and delayed review. FastAPI owns every formal
decision; Agent output remains a proposal and never writes formal state.

## Scope

BE-004 owns:

- learning context and versioned eight-dimension profile state;
- profile change proposals and student disputes;
- validated learning paths and ordered steps;
- reusable task definitions, immutable task versions, and student instances;
- deterministic assessment records;
- current mastery plus append-only mastery history;
- delayed review schedules, attempts, due queries, and rescheduling;
- renderer-facing Pydantic/Zod contracts and generated OpenAPI client updates;
- student APIs for current profile/path/today/mastery/due reviews and the
  write APIs needed to start tasks, submit assessment facts, dispute profiles,
  and reschedule reviews.

BE-004 does not own:

- code execution or hidden-test isolation (BE-005);
- LangGraph.js orchestration or Agent provider calls (BE-006/BE-007);
- generated learning resources (BE-007);
- the complete course asset catalogue (BE-009);
- admin monitoring and maintenance APIs (BE-010).

Until BE-009 supplies course and knowledge-node tables, course/node identifiers
are stable UUID references without foreign keys. BE-009 may add those foreign
keys after importing validated assets; BE-004 does not create placeholder
course content.

## Chosen Architecture

Use normalized PostgreSQL tables and small deterministic domain services. This
matches the frozen design and keeps transaction, query, and uniqueness rules
visible to the database.

Rejected alternatives:

1. Full Event Sourcing is rejected because V1.0 explicitly stores current
   formal state in PostgreSQL and uses events only for evidence, audit, and
   Outbox delivery.
2. A single JSONB learning-state aggregate is rejected because it cannot
   enforce profile-version monotonicity, ordered path steps, immutable task
   versions, unique mastery state, or review evidence relationships.

## Persistence Model

Migration `0004_learning_loop` adds the following normalized tables.

### Context and profiles

- `learning_contexts`: one current row per student, containing goal,
  background, progress, daily minutes, media preferences, deadline, mode,
  device constraints, and `version`.
- `profile_versions`: immutable profile headers with a monotonic
  `(student_id, version)` key and the evidence event that caused the version.
- `profile_dimension_scores`: one row per profile version, dimension, and
  optional knowledge-node/ability-cluster key. Scores and confidence are
  constrained to `0..1`; support level is constrained to `0..3`.
- `profile_change_proposals`: Agent or deterministic proposals with
  `PROPOSED/ACCEPTED/REJECTED` state. Accepting a proposal still passes through
  the deterministic projector.
- `profile_disputes`: append-only student disputes tied to a profile version.

The eight dimensions are stable enum values: concept knowledge, execution
model, implementation, decomposition, debugging, testing, transfer, and
independence/support.

### Paths and tasks

- `learning_paths`: versioned current/former paths per student and course.
- `learning_path_steps`: ordered path steps with node ID, activity kind,
  estimated minutes, source proposal metadata, and validation outcome.
- `task_definitions`: reusable task identity and title.
- `task_versions`: immutable JSON snapshot containing prompt, tests policy,
  hint policy, resource version references, mastery policy, and scenario key.
- `task_instances`: one student execution of a task version. A partial unique
  index prevents more than one active instance for the same student/version
  and active key.
- `task_status_history`: append-only status transitions.

Starting a task copies the task-version snapshot to the instance. No update
path is exposed for either snapshot after publication/start.

### Assessment, mastery, and reviews

- `assessment_results`: immutable deterministic inputs including correctness,
  hidden-test result, hints used, support level, independence score,
  transfer score, and source evidence IDs.
- `mastery_states`: one current row per student/course/node with enum state and
  optimistic `version`.
- `mastery_state_history`: append-only transitions with reason and evidence.
- `review_schedules`: review variant, due time, hint ceiling, status, and
  reschedule history fields.
- `review_attempts`: immutable review outcome and evidence link.

`INITIAL_MASTERY` requires an active review schedule in the same transaction.
`STABLE_MASTERY` requires a passed delayed-review attempt whose evidence is
newer than the initial-mastery transition.

## Deterministic Policies

### Profile projection

The projector consumes accepted evidence facts and an expected current
profile version. It creates a new immutable profile version and dimension rows
only when the expected version matches. Conflicts return `CONFLICT`; no silent
overwrite is allowed. Professional background and media preference may change
examples or presentation but never modify base knowledge scores.

### Path validation

For each proposed step, the validator applies rules in this order:

1. place due reviews before new learning;
2. insert missing prerequisites;
3. split activities exceeding the available daily time;
4. reject a step without a mastery policy;
5. reject or template-fallback when resources are unavailable;
6. replace duplicate active work with a scenario variant;
7. reject nodes whose formal state does not permit entry.

Platform failures never create remediation steps. Validation returns both the
corrected path and structured findings; only a validated path can become
current or compile tasks.

### Task compilation

Compilation is pure and deterministic for the same validated path step,
definition, policy versions, and scenario key. Published task versions and
started instance snapshots are immutable. Retrying a start command with the
same idempotency key returns the existing active instance.

### Assessment and mastery

Deterministic correctness and hidden tests are required for a passing
assessment. Hint/support usage reduces independence and can cap the result at
`PASSED_WITH_HELP`. The state transitions are:

- `UNSEEN -> LEARNING` on the first accepted attempt;
- `LEARNING -> PASSED_WITH_HELP` when passing requires support above policy;
- `LEARNING/PASSED_WITH_HELP/REVIEW_REQUIRED -> INITIAL_MASTERY` when correctness,
  independence, and transfer thresholds pass;
- `INITIAL_MASTERY -> REVIEW_REQUIRED` when the scheduled review becomes due;
- `REVIEW_REQUIRED/INITIAL_MASTERY -> STABLE_MASTERY` only after an unassisted
  delayed-review variant passes;
- a failed review remains or returns to `REVIEW_REQUIRED` and schedules a new
  variant without decreasing the underlying ability score merely because the
  student postponed it or the platform failed.

Every transition appends history and emits an Outbox event in the same UoW.

### Review scheduling

Initial mastery creates the first review using a policy interval and an
explicit UTC timestamp. Due queries compare stored UTC timestamps with an
injected clock so tests and demos use real persisted dates without sleeping.
Students may postpone within the policy limit; postponement changes only the
schedule and audit trail, never profile/mastery scores.

## APIs and Contracts

Read APIs:

- `GET /api/v1/profiles/current`
- `GET /api/v1/learning/today`
- `GET /api/v1/paths/current`
- `GET /api/v1/mastery`
- `GET /api/v1/reviews/due`

Write APIs:

- `POST /api/v1/profiles/disputes`
- `POST /api/v1/tasks/{task_version_id}/start`
- `POST /api/v1/tasks/{task_instance_id}/submit`
- `POST /api/v1/reviews/{review_id}/reschedule`

All reads are scoped to the authenticated student and tenant. Every write
requires `Idempotency-Key`, validates the same scope on replay, records audit,
and commits state plus Outbox atomically. Validation failures use
`VALIDATION_ERROR`; optimistic or state conflicts use `CONFLICT`; inaccessible
objects use a non-disclosing `NOT_FOUND` or `FORBIDDEN` according to the
existing authorization policy.

## Data Flow

1. Evidence is accepted by the BE-003 append-only service.
2. The profile projector creates the next version from evidence facts.
3. A path proposal enters the deterministic validator and becomes a corrected,
   persisted path only after all findings are resolved.
4. The task compiler publishes an immutable version and start creates an
   immutable student instance snapshot.
5. Submission records assessment facts; BE-005 will later supply sandbox facts
   through this same interface.
6. The mastery engine transitions formal state and creates or completes a
   review schedule atomically.
7. Today/due queries prioritize persisted overdue reviews before new path work.

## Testing Strategy

- Migration tests cover upgrade/downgrade, unique keys, checks, partial active
  indexes, and required relationships.
- Profile tests cover version conflicts, monotonic history, evidence linkage,
  and dimension bounds.
- Path tests cover prerequisite insertion, time splitting, duplicate variants,
  missing policy/resource failure, and due-review priority.
- Task tests prove definition reuse, version determinism, active uniqueness,
  and snapshot immutability after definition changes.
- Mastery tests cover every legal/illegal transition and the
  `PASSED_WITH_HELP` high-order unlock cap.
- Review tests use an injected UTC clock for due, postpone, failure, platform
  error, and stable-mastery evidence gates.
- API tests cover tenant/student isolation, idempotent replay, stable errors,
  audit/Outbox writes, OpenAPI generation, and Pydantic/Zod parity.

## Rollback and Compatibility

Migration downgrade removes only BE-004 tables in reverse dependency order.
BE-003 evidence/audit/outbox/idempotency tables and existing identity records
remain intact. Contract additions are additive; existing BE-001 through BE-003
wire models and endpoints are unchanged.
