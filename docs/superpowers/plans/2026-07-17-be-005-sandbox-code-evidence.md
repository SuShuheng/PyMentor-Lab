# BE-005 Sandbox and Code Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute student Python in hardened per-phase Linux containers and persist bounded revision, test, hint, trace, and assessment evidence without treating platform failures as student failures.

**Architecture:** FastAPI owns authenticated commands, private task-policy lookup, persistence, evidence, audit, and Outbox. A signed internal Sandbox Supervisor creates one fixed-image container per visible or hidden phase; a standard-library harness validates/instruments source and returns one bounded framed result. External execution occurs between short database transactions.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16, Docker Engine Linux containers, pytest, Ruff, mypy, Zod, TypeScript, pnpm, OpenAPI TypeScript.

## Global Constraints

- The only trusted untrusted-code boundary is a fresh Linux container; the host subprocess adapter is test-only and cannot create formal submission evidence.
- Client requests never provide tests, images, commands, paths, mounts, environment variables, or resource limits.
- Visible and hidden phases use different fresh containers; hidden cases never enter student-visible snapshots, files, logs, or responses.
- Job containers use `network=none`, read-only root, size-limited tmpfs, zero capabilities, `no-new-privileges`, built-in seccomp, no host mounts/devices/socket, one CPU, 128 MiB memory, 32 PIDs, and fixed cleanup.
- Source is at most 65,536 UTF-8 bytes; stdout/stderr are 32,768 bytes each; results contain at most 256 tests and 1,000 trace frames.
- Platform failures never emit `ASSESSMENT_RECORDED` and never reduce mastery; student-caused terminal outcomes may emit deterministic evidence.
- Source, hidden cases, captured output, trace locals, HMAC material, container IDs, and host paths never enter logs, audit detail, or Outbox payloads.
- Every write command validates auth, tenant/student scope, schema, idempotency, domain state, and audit context.
- Every formal run transition appends history and Outbox in the same transaction; Docker work never runs inside a database transaction.
- Use Red-Green-Refactor, focused tests per slice, Pydantic/Zod conformance for contract changes, and Conventional Commits.

---

### Task 1: Freeze sandbox/code contracts and public task projection

**Files:**

- Modify: `backend/app/contracts/sandbox.py`
- Modify: `backend/app/contracts/__init__.py`
- Modify: `backend/app/contracts/learning.py`
- Modify: `packages/contracts/src/sandbox.ts`
- Modify: `packages/contracts/src/learning.ts`
- Modify: `packages/contracts/src/conformance.ts`
- Modify: `packages/contracts/src/export-json-schema.ts`
- Modify: `backend/tests/test_contracts_parity.py`
- Modify: `packages/contracts/src/contracts.test.ts`
- Create: `backend/app/task_policy.py`
- Create: `backend/tests/test_task_policy.py`
- Modify: `backend/app/api/tasks.py`
- Modify: `backend/tests/test_learning_api.py`

**Interfaces:**

- Consumes: BE-004 `TaskInstance.snapshot` and existing `SandboxResult` bootstrap contract.
- Produces: `CodeRunMode`, `CodeRunStatus`, `TestVisibility`, `SandboxComparison`, `SandboxExecutionRequest`, `CodeRunRequest`, `CodeSubmissionRequest`, `CodeRunView`, `HintRequest`, `HintUsageView`, `parse_task_policy()`, and `public_task_snapshot()`.

- [ ] **Step 1: Write Red contract and redaction tests**

Add Pydantic/Zod fixtures for every new model and this focused policy test:

```python
def test_public_task_snapshot_removes_hidden_cases() -> None:
    snapshot = {
        "prompt": "Return the sum",
        "tests_policy": {
            "entrypoint": {"kind": "FUNCTION", "name": "solve"},
            "allowed_imports": ["math"],
            "visible": [
                {
                    "id": "visible-basic",
                    "args": [[1, 2]],
                    "kwargs": {},
                    "expected": 3,
                    "comparison": "EQUAL",
                    "transfer": False,
                }
            ],
            "hidden": [
                {
                    "id": "hidden-boundary",
                    "args": [[0, 0]],
                    "kwargs": {},
                    "expected": 0,
                    "comparison": "EQUAL",
                    "transfer": True,
                }
            ],
        },
        "hint_policy": {
            "max_level": 1,
            "hints": [
                {"key": "inspect-bound", "level": 1, "content": "Check the stop.",
                 "independence_cost": 10}
            ],
        },
        "mastery_policy": {"independence_min": 0.7},
        "resource_versions": {},
        "scenario_key": "sum-v1",
    }

    public = public_task_snapshot(snapshot)

    assert "hidden" not in public["tests_policy"]
    assert public["tests_policy"]["visible"][0]["id"] == "visible-basic"
    assert public["hint_policy"] == {"max_level": 1}
```

Update the task-start API test to assert the response contains no hidden IDs,
expected hidden values, or hint content.

- [ ] **Step 2: Run the tests Red**

Run:

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider backend/tests/test_task_policy.py `
  backend/tests/test_contracts_parity.py backend/tests/test_learning_api.py -q
pnpm contracts:check
```

Expected: Python collection/import failures for the new contract names and
`task_policy`; Zod conformance fails because the schemas are absent.

- [ ] **Step 3: Implement the exact contract vocabulary**

Add these enum values and model boundaries in both Pydantic and Zod:

```python
class CodeRunMode(StrEnum):
    RUN = "RUN"
    TRACE = "TRACE"
    SUBMIT = "SUBMIT"


class CodeRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    USER_ERROR = "USER_ERROR"
    PLATFORM_ERROR = "PLATFORM_ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class TestVisibility(StrEnum):
    VISIBLE = "VISIBLE"
    HIDDEN = "HIDDEN"


class SandboxComparison(StrEnum):
    EQUAL = "EQUAL"
    APPROX = "APPROX"
    UNORDERED = "UNORDERED"
    MATCHES = "MATCHES"


class SandboxResourceUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu_ms: int = Field(ge=0)
    wall_ms: int = Field(ge=0)
    peak_memory_kb: int = Field(ge=0)
    exit_code: int | None = None


class CodeRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_instance_id: str = Field(min_length=1)
    source_code: str = Field(min_length=1, max_length=65_536)
    mode: Literal[CodeRunMode.RUN, CodeRunMode.TRACE]
    expected_task_version: int = Field(ge=1)
    trace_enabled: bool = False


class CodeSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_instance_id: str = Field(min_length=1)
    source_code: str = Field(min_length=1, max_length=65_536)
    expected_task_version: int = Field(ge=1)


class HintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int = Field(ge=1, le=3)
    revision_id: str | None = None
    expected_task_version: int = Field(ge=1)
```

Revise `SandboxTestCaseResult`, `TraceFrame`, and `SandboxResult` to use
visibility/display-name/truncation fields, trace `sequence`, `trace_frames`, and
`SandboxResourceUsage`. Define strict private task-policy models for entrypoint,
case, hint, and execution policy. Define `CodeRevisionView`, `CodeRunView`, and
`HintUsageView` with no source, private policy, host path, or container ID.

- [ ] **Step 4: Implement private parsing and public projection**

In `backend/app/task_policy.py`, expose these exact functions:

```python
ALLOWED_IMPORTS = frozenset(
    {"math", "statistics", "collections", "itertools", "functools",
     "decimal", "fractions", "re", "string", "json"}
)


def parse_task_policy(snapshot: dict[str, Any]) -> CompiledTaskPolicy:
    tests = SandboxTaskTests.model_validate(snapshot.get("tests_policy"))
    hints = SandboxHintPolicy.model_validate(snapshot.get("hint_policy"))
    if not set(tests.allowed_imports) <= ALLOWED_IMPORTS:
        raise InvalidTaskPolicy("task requests a non-allowlisted import")
    if len(tests.visible) + len(tests.hidden) > 256:
        raise InvalidTaskPolicy("task contains more than 256 cases")
    return CompiledTaskPolicy(tests=tests, hints=hints)


def public_task_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    policy = parse_task_policy(snapshot)
    result = copy.deepcopy(snapshot)
    result["tests_policy"] = {
        "entrypoint": policy.tests.entrypoint.model_dump(mode="json"),
        "allowed_imports": policy.tests.allowed_imports,
        "visible": [case.public_view() for case in policy.tests.visible],
    }
    result["hint_policy"] = {"max_level": policy.hints.max_level}
    return result
```

Change `_start_response()` in `backend/app/api/tasks.py` to pass only
`public_task_snapshot(instance.snapshot)`.

- [ ] **Step 5: Run Green gates**

Run:

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider backend/tests/test_task_policy.py `
  backend/tests/test_contracts_parity.py backend/tests/test_learning_api.py -q
pnpm contracts:check
pnpm --filter @pymentor/contracts test
pnpm typecheck
```

Expected: all focused tests pass and conformance reports the expanded model count.

- [ ] **Step 6: Commit the contract slice**

```powershell
git add -- backend/app/contracts backend/app/task_policy.py backend/app/api/tasks.py `
  backend/tests/test_task_policy.py backend/tests/test_contracts_parity.py `
  backend/tests/test_learning_api.py packages/contracts
git commit -m "feat(backend): define sandbox code contracts"
```

---

### Task 2: Add run, revision, test, and hint persistence

**Files:**

- Create: `backend/app/models/code.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/migrations/versions/0005_sandbox_code_evidence.py`
- Create: `backend/tests/test_code_models.py`
- Modify: `backend/tests/test_migrations.py`

**Interfaces:**

- Consumes: Task 1 enums and BE-002/003/004 tenant, user, idempotency, evidence,
  and task-instance tables.
- Produces: `CodeRevision`, `CodeRun`, `CodeRunStatusHistory`, `TestResult`, and
  `HintUsage` ORM models plus migration constraints.

- [ ] **Step 1: Write Red model and migration tests**

Add `EXPECTED_0005_TABLES` and assertions for:

```python
EXPECTED_0005_TABLES = {
    "code_revisions",
    "code_runs",
    "code_run_status_history",
    "test_results",
    "hint_usages",
}


def test_code_run_active_uniqueness_is_partial() -> None:
    index = next(
        item for item in CodeRun.__table__.indexes
        if item.name == "uq_code_run_active_task"
    )
    assert index.unique is True
    assert index.dialect_options["postgresql"]["where"] is not None


def test_0005_tables_exist_after_round_trip() -> None:
    cfg = _make_config()
    command.upgrade(cfg, "head")
    assert EXPECTED_0005_TABLES <= set(inspect(engine).get_table_names())
```

Also assert revision source-byte, sequence, run-version, hint-level/cost, and test
ordinal constraints by name.

- [ ] **Step 2: Run model/migration tests Red**

```powershell
$dbLine = (Select-String -LiteralPath '.env.example' -Pattern '^PYMENTOR_DATABASE_URL=').Line
$env:PYMENTOR_DATABASE_URL = $dbLine.Substring($dbLine.IndexOf('=') + 1).Replace('@localhost:', '@127.0.0.1:') + '?connect_timeout=5'
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider backend/tests/test_code_models.py `
  backend/tests/test_migrations.py -q
```

Expected: import/table failures for the five new models/tables.

- [ ] **Step 3: Implement all five ORM models**

Use stable SQLAlchemy enums backed by strings. The core run model must contain:

```python
class CodeRun(Base):
    __tablename__ = "code_runs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_code_runs_run_id"),
        CheckConstraint("version >= 1", name="ck_code_run_version_positive"),
        Index(
            "uq_code_run_active_task",
            "task_instance_id",
            unique=True,
            postgresql_where=text("status IN ('QUEUED', 'RUNNING')"),
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    task_instance_id: Mapped[UUID] = mapped_column(ForeignKey("task_instances.id"), index=True)
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("code_revisions.id"), index=True)
    idempotency_key_id: Mapped[UUID] = mapped_column(ForeignKey("idempotency_keys.id"), unique=True)
    mode: Mapped[CodeRunMode] = mapped_column(sa_enum(CodeRunMode), nullable=False)
    status: Mapped[CodeRunStatus] = mapped_column(sa_enum(CodeRunStatus), nullable=False)
    policy_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    trace_frames: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    evidence_event_id: Mapped[str | None] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

Implement the remaining fields and named constraints exactly as specified in the
design, including `octet_length(source_code) BETWEEN 1 AND 65536` and all required
tenant foreign keys/indexes.

- [ ] **Step 4: Implement migration 0005 and downgrade**

Create the same columns, enum storage, checks, unique constraints, and active partial
index as the ORM metadata. `downgrade()` drops:

```python
def downgrade() -> None:
    op.drop_table("hint_usages")
    op.drop_table("test_results")
    op.drop_table("code_run_status_history")
    op.drop_table("code_runs")
    op.drop_table("code_revisions")
```

- [ ] **Step 5: Run Green persistence gates**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider backend/tests/test_code_models.py `
  backend/tests/test_migrations.py -q
uv run ruff check backend/app/models/code.py backend/tests/test_code_models.py
uv run mypy backend/app/models/code.py
```

Expected: model/migration tests pass, including upgrade/downgrade/upgrade.

- [ ] **Step 6: Commit persistence**

```powershell
git add -- backend/app/models backend/migrations/versions/0005_sandbox_code_evidence.py `
  backend/tests/test_code_models.py backend/tests/test_migrations.py
git commit -m "feat(backend): persist sandbox code evidence"
```

---

### Task 3: Implement deterministic revision, lifecycle, hint, and evidence policy

**Files:**

- Create: `backend/app/code_runs.py`
- Create: `backend/app/hints.py`
- Create: `backend/tests/test_code_runs.py`
- Create: `backend/tests/test_hints.py`

**Interfaces:**

- Consumes: Task 1 policies/contracts, Task 2 models, BE-003 evidence/UoW, and
  BE-004 task snapshots.
- Produces: `create_revision()`, `reserve_code_run()`, `transition_code_run()`,
  `finalize_code_run()`, `recover_stale_runs()`, `record_hint_usage()`, and
  `assessment_facts_for_run()`.

- [ ] **Step 1: Write Red domain tests**

Cover revision digest reuse, one active run, legal/illegal transitions, history,
hint order/budget, deterministic assessment facts, platform suppression, and stale
recovery. Include:

```python
def test_platform_error_never_creates_assessment_evidence(db_session, active_run) -> None:
    result = SandboxResult.platform_failure(
        run_id=active_run.run_id,
        category="ENGINE_UNAVAILABLE",
        message="runner unavailable",
    )
    finalized = finalize_code_run(db_session, active_run.id, result, now=NOW)
    assert finalized.status == CodeRunStatus.PLATFORM_ERROR
    assert finalized.evidence_event_id is None
    assert db_session.scalar(
        select(func.count()).select_from(EvidenceEvent).where(
            EvidenceEvent.task_id == active_run.task_instance_id,
            EvidenceEvent.event_type == "ASSESSMENT_RECORDED",
        )
    ) == 0


def test_assessment_facts_include_hint_cost_and_transfer(db_session, submit_run) -> None:
    facts = assessment_facts_for_run(db_session, submit_run)
    assert facts == {
        "correct": True,
        "hidden_tests_passed": True,
        "hints_used": 2,
        "support_level": 2,
        "independence_score": 0.65,
        "transfer_score": 1.0,
        "platform_error": False,
    }
```

- [ ] **Step 2: Run domain tests Red**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider backend/tests/test_code_runs.py `
  backend/tests/test_hints.py -q
```

Expected: module/function import failures.

- [ ] **Step 3: Implement revision and run state services**

Expose exact transition rules and signatures:

```python
ALLOWED_RUN_TRANSITIONS = {
    CodeRunStatus.QUEUED: {
        CodeRunStatus.RUNNING,
        CodeRunStatus.CANCELLED,
        CodeRunStatus.PLATFORM_ERROR,
    },
    CodeRunStatus.RUNNING: {
        CodeRunStatus.COMPLETED,
        CodeRunStatus.USER_ERROR,
        CodeRunStatus.PLATFORM_ERROR,
        CodeRunStatus.TIMEOUT,
        CodeRunStatus.CANCELLED,
    },
}


def create_revision(
    db: Session, *, tenant_id: UUID, student_id: UUID,
    task_instance_id: UUID, source_code: str,
) -> CodeRevision:
    encoded = source_code.encode("utf-8")
    if not 1 <= len(encoded) <= 65_536:
        raise InvalidCodeCommand("source must contain 1..65536 UTF-8 bytes")
    digest = hashlib.sha256(encoded).hexdigest()
    existing = db.scalar(
        select(CodeRevision).where(
            CodeRevision.tenant_id == tenant_id,
            CodeRevision.student_id == student_id,
            CodeRevision.task_instance_id == task_instance_id,
            CodeRevision.source_digest == digest,
        )
    )
    if existing is not None:
        return existing
    latest = db.scalar(
        select(CodeRevision)
        .where(CodeRevision.task_instance_id == task_instance_id)
        .order_by(CodeRevision.sequence.desc())
        .limit(1)
        .with_for_update()
    )
    revision = CodeRevision(
        tenant_id=tenant_id,
        student_id=student_id,
        task_instance_id=task_instance_id,
        sequence=(latest.sequence if latest else 0) + 1,
        parent_revision_id=latest.id if latest else None,
        source_digest=digest,
        source_code=source_code,
    )
    db.add(revision)
    db.flush()
    return revision


def reserve_code_run(
    db: Session, *, task: TaskInstance, revision: CodeRevision,
    idempotency: IdempotencyKey, mode: CodeRunMode,
    policy_snapshot: dict[str, Any], trace_id: str, now: datetime,
) -> CodeRun:
    encoded_policy = json.dumps(
        policy_snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    run = CodeRun(
        run_id=f"run_{uuid4().hex}",
        tenant_id=task.tenant_id,
        student_id=task.student_id,
        task_instance_id=task.id,
        revision_id=revision.id,
        idempotency_key_id=idempotency.id,
        mode=mode,
        status=CodeRunStatus.QUEUED,
        policy_digest=hashlib.sha256(encoded_policy).hexdigest(),
        policy_snapshot=policy_snapshot,
        version=1,
        requested_at=now,
        deadline_at=now + timedelta(seconds=15),
    )
    db.add(run)
    db.flush()
    db.add(CodeRunStatusHistory(
        tenant_id=run.tenant_id, code_run_id=run.id, from_status=None,
        to_status=run.status, reason="RUN_RESERVED", trace_id=trace_id, created_at=now,
    ))
    db.add(outbox_for_run(run, event_type="CODE_RUN_QUEUED", trace_id=trace_id))
    db.flush()
    return run


def transition_code_run(
    db: Session, run: CodeRun, target: CodeRunStatus, *,
    reason: str, trace_id: str, now: datetime,
) -> CodeRun:
    current = run.status
    if target not in ALLOWED_RUN_TRANSITIONS.get(current, set()):
        raise IllegalCodeRunTransition(f"{current.value} -> {target.value}")
    run.status = target
    run.version += 1
    if target == CodeRunStatus.RUNNING:
        run.started_at = now
    if target in TERMINAL_RUN_STATUSES:
        run.completed_at = now
    db.add(CodeRunStatusHistory(
        tenant_id=run.tenant_id, code_run_id=run.id, from_status=current,
        to_status=target, reason=reason, trace_id=trace_id, created_at=now,
    ))
    db.add(outbox_for_run(
        run, event_type=f"CODE_RUN_{target.value}", trace_id=trace_id,
    ))
    db.flush()
    return run
```

`outbox_for_run()` includes only run/task IDs, mode, status, version, and policy
digest. The service row-locks task/run rows before invoking these functions. No
transition function commits; the caller owns the UoW.

- [ ] **Step 4: Implement hints and evidence formulas**

`record_hint_usage()` row-locks task/hint history and requires requested level equal
to `previous_level + 1`. `assessment_facts_for_run()` uses:

```python
independence = max(0.0, 1.0 - sum(hint.cost for hint in hints) / 100.0)
transfer = (
    sum(1 for row in hidden_transfer if row.passed) / len(hidden_transfer)
    if hidden_transfer
    else float(bool(hidden_rows) and all(row.passed for row in hidden_rows))
)
```

`finalize_code_run()` validates all result bounds again, persists normalized test
rows, maps inner outcomes to formal terminal status, and emits `ASSESSMENT_RECORDED`
only for `SUBMIT` plus a non-platform terminal outcome.

- [ ] **Step 5: Implement stale recovery**

```python
def claim_stale_runs(db: Session, *, now: datetime, limit: int = 50) -> list[CodeRun]:
    statement = (
        select(CodeRun)
        .where(
            CodeRun.status.in_([CodeRunStatus.QUEUED, CodeRunStatus.RUNNING]),
            CodeRun.deadline_at <= now,
        )
        .order_by(CodeRun.deadline_at, CodeRun.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(db.scalars(statement))
```

For each claimed run, cleanup occurs outside the selecting transaction; a final UoW
row-locks it again, verifies it remains non-terminal, records `PLATFORM_ERROR`, and
saves the linked idempotency response.

- [ ] **Step 6: Run Green domain gates and commit**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider backend/tests/test_code_runs.py `
  backend/tests/test_hints.py -q
uv run ruff check backend/app/code_runs.py backend/app/hints.py `
  backend/tests/test_code_runs.py backend/tests/test_hints.py
uv run mypy backend/app/code_runs.py backend/app/hints.py
git add -- backend/app/code_runs.py backend/app/hints.py `
  backend/tests/test_code_runs.py backend/tests/test_hints.py
git commit -m "feat(backend): decide code run evidence"
```

---

### Task 4: Implement signed Supervisor protocol and bounded framing

**Files:**

- Create: `sandbox/protocol.py`
- Create: `sandbox/tests/test_protocol.py`

**Interfaces:**

- Consumes: Task 1 internal execution request/result wire shape.
- Produces: `canonical_json()`, `sign_request()`, `verify_request()`,
  `encode_frame()`, `decode_frame()`, and `NonceCache`.

- [ ] **Step 1: Write Red protocol tests**

Test canonical stability, NaN rejection, wrong digest/signature, timestamp skew,
nonce replay, body size, magic prefix, declared-length mismatch, duplicate/trailing
frames, and maximum response size.

```python
def test_signature_binds_timestamp_nonce_and_body() -> None:
    body = canonical_json({"run_id": "run_1", "source": "print(1)"})
    signed = sign_request(
        body,
        method="POST",
        path="/internal/v1/executions",
        secret=b"x" * 32,
        timestamp=1_752_700_000,
        nonce="n1",
    )
    verify_request(
        body,
        method="POST",
        path="/internal/v1/executions",
        headers=signed,
        secret=b"x" * 32,
        now=1_752_700_010,
        nonces=NonceCache(ttl_seconds=60, capacity=100),
    )
    with pytest.raises(ProtocolAuthenticationError):
        verify_request(
            body + b" ", method="POST", path="/internal/v1/executions",
            headers=signed, secret=b"x" * 32,
            now=1_752_700_010, nonces=NonceCache(60, 100),
        )
```

- [ ] **Step 2: Run protocol tests Red**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider sandbox/tests/test_protocol.py -q
```

Expected: `sandbox.protocol` import failure.

- [ ] **Step 3: Implement canonical signing and verification**

Use only standard library primitives:

```python
MAGIC = b"PYMENTOR_SANDBOX_V1\n"
MAX_REQUEST_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 512 * 1024


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def signature_message(
    method: str, path: str, timestamp: int, nonce: str, digest: str
) -> bytes:
    return f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{digest}".encode("ascii")


def sign_request(
    body: bytes, *, method: str, path: str, secret: bytes,
    timestamp: int, nonce: str,
) -> dict[str, str]:
    digest = hashlib.sha256(body).hexdigest()
    signature = hmac.new(
        secret,
        signature_message(method, path, timestamp, nonce, digest),
        hashlib.sha256,
    )
    return {
        "x-sandbox-timestamp": str(timestamp),
        "x-sandbox-nonce": nonce,
        "x-sandbox-digest": digest,
        "x-sandbox-signature": signature.hexdigest(),
    }
```

`verify_request()` enforces 30-second skew, 32-byte minimum secret, nonce syntax/TTL,
exact digest, and constant-time signature comparison before parsing JSON.

- [ ] **Step 4: Implement strict framing**

The frame format is `MAGIC + eight ASCII hex length bytes + b"\n" + canonical JSON`.
`decode_frame()` requires exactly one complete frame and no trailing bytes. It returns
a dict only after JSON object/type/size validation.

- [ ] **Step 5: Run Green gates and commit**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider sandbox/tests/test_protocol.py -q
uv run ruff check sandbox/protocol.py sandbox/tests/test_protocol.py
uv run mypy sandbox/protocol.py
git add -- sandbox/protocol.py sandbox/tests/test_protocol.py
git commit -m "feat(sandbox): authenticate bounded runner protocol"
```

---

### Task 5: Build AST policy, deterministic tracing, and runtime harness

**Files:**

- Create: `sandbox/policy.py`
- Create: `sandbox/tracing.py`
- Create: `sandbox/harness.py`
- Create: `sandbox/tests/test_policy.py`
- Create: `sandbox/tests/test_tracing.py`
- Replace: `sandbox/runner.py`
- Modify: `sandbox/tests/test_runner.py`

**Interfaces:**

- Consumes: Task 4 framing and the normalized internal request.
- Produces: `validate_source()`, `instrument_source()`, `sanitize_value()`,
  `execute_request()`, and `python -I -S sandbox/harness.py` entrypoint.

- [ ] **Step 1: Write Red AST security tests**

Parameterize syntax/import/traversal/subprocess/dynamic-import/reflection/tamper cases:

```python
@pytest.mark.parametrize(
    "source, category",
    [
        ("import os", "IMPORT_DENIED"),
        ("from subprocess import run", "IMPORT_DENIED"),
        ("__import__('socket')", "CALL_DENIED"),
        ("compile('1+1', '<x>', 'eval')", "CALL_DENIED"),
        ("open('../../secret')", "CALL_DENIED"),
        ("globals()['_pymentor_trace'] = None", "CALL_DENIED"),
        ("_pymentor_trace = lambda: None", "RESERVED_NAME"),
    ],
)
def test_policy_rejects_dangerous_source(source: str, category: str) -> None:
    with pytest.raises(StudentPolicyError) as caught:
        validate_source(source, allowed_imports=frozenset({"math"}))
    assert caught.value.category == category
```

- [ ] **Step 2: Write Red trace/result tests**

Prove deterministic frame order, sorted/sanitized locals, cycle/address removal,
frame truncation, stdout/stderr truncation, visible/hidden display names, function
and script cases, comparison modes, syntax/runtime/user timeout results, and no raw
traceback/control-frame injection.

- [ ] **Step 3: Run harness tests Red**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider sandbox/tests/test_policy.py `
  sandbox/tests/test_tracing.py sandbox/tests/test_runner.py -q
```

Expected: new modules/functions absent.

- [ ] **Step 4: Implement `PolicyVisitor`**

Implement a deny-first AST visitor with exact entrypoint:

```python
def validate_source(source: str, *, allowed_imports: frozenset[str]) -> ast.Module:
    if not 1 <= len(source.encode("utf-8")) <= 65_536:
        raise StudentPolicyError("SOURCE_SIZE", "source must contain 1..65536 bytes")
    try:
        tree = ast.parse(source, mode="exec", type_comments=True)
    except SyntaxError as exc:
        raise StudentSyntaxError(line=exc.lineno or 1, message=exc.msg) from None
    PolicyVisitor(allowed_imports).visit(tree)
    return tree
```

The visitor permits only named allowlisted imports, rejects relative/star import,
denied calls/names, reserved-prefix bindings, dunder attribute access, `Global` and
`Nonlocal` for reserved names, and an AST node/depth budget.

- [ ] **Step 5: Implement deterministic instrumentation and sanitation**

`TraceTransformer` inserts a callback expression before statements while preserving
line numbers. The callback receives event/line/function and captures locals through
the trusted harness. `sanitize_value()` accepts only scalar/list/tuple/dict shapes,
sorts dictionary keys, replaces cycles, removes memory addresses, and enforces depth,
item, key, and rendered-value bounds.

- [ ] **Step 6: Implement trusted parent/child harness**

`execute_request()` must:

1. validate the request dict and source before spawning;
2. create a clean source file under the container tmpfs;
3. spawn an unprivileged Python child with pipes, isolated mode, empty environment,
   fixed working directory, and POSIX resource limits;
4. send one declarative case at a time and keep hidden cases in the parent;
5. collect bounded output/tests/trace/resource usage;
6. classify student syntax/runtime/policy/resource/timeout separately from harness
   exceptions;
7. return one JSON-serializable bounded result.

The `main()` function reads one request from stdin and writes only
`encode_frame(execute_request(request))` to the original container stdout.

- [ ] **Step 7: Run Green harness gates and commit**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider sandbox/tests/test_policy.py `
  sandbox/tests/test_tracing.py sandbox/tests/test_runner.py -q
uv run ruff check sandbox
uv run mypy sandbox/policy.py sandbox/tracing.py sandbox/harness.py sandbox/runner.py
git add -- sandbox
git commit -m "feat(sandbox): execute bounded Python cases and traces"
```

---

### Task 6: Add hardened Docker executor and signed Supervisor service

**Files:**

- Create: `sandbox/executor.py`
- Create: `sandbox/service.py`
- Create: `sandbox/tests/test_executor.py`
- Create: `sandbox/tests/test_service.py`
- Replace: `infra/sandbox.Dockerfile`
- Create: `infra/sandbox-runtime.Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `backend/app/config.py`
- Modify: `pyproject.toml`

**Interfaces:**

- Consumes: Task 4 protocol and Task 5 harness.
- Produces: `SandboxExecutor` protocol, `DockerCliExecutor.execute()/cancel()`,
  internal signed Supervisor endpoints, runtime/Supervisor images, and validated
  settings.

- [ ] **Step 1: Write Red executor/service tests**

Use a fake process runner to assert the exact Docker argv and prove no request value
can replace image, entrypoint, command, mount, environment, user, or resource flags.
Test invalid signature/body/timestamp/nonce, duplicate request, cancellation, malformed
container output, timeout kill/removal, and cleanup failure classification.

```python
def test_docker_argv_is_hardened(fake_process_runner, execution_request) -> None:
    executor = DockerCliExecutor(
        image="pymentor-sandbox-runtime@sha256:" + "a" * 64,
        process_runner=fake_process_runner,
    )
    executor.execute(execution_request)
    argv = fake_process_runner.started_argv
    assert ["--network", "none"] == argv[argv.index("--network"):][:2]
    assert "--read-only" in argv
    assert ["--cap-drop", "ALL"] == argv[argv.index("--cap-drop"):][:2]
    assert ["--security-opt", "no-new-privileges=true"] == argv[
        argv.index("--security-opt"):
    ][:2]
    assert "--privileged" not in argv
    assert "--volume" not in argv
    assert execution_request.source not in argv
```

- [ ] **Step 2: Run tests Red**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider sandbox/tests/test_executor.py `
  sandbox/tests/test_service.py -q
```

Expected: executor/service imports fail.

- [ ] **Step 3: Implement fixed Docker executor**

Build argv from constants and validated numbers, never through a shell:

```python
def docker_create_argv(self, run_id: str, expires_at: int) -> list[str]:
    return [
        "docker", "create", "--name", container_name(run_id),
        "--label", f"pymentor.run_id={run_id}",
        "--label", "pymentor.protocol=1",
        "--label", f"pymentor.expires_at={expires_at}",
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges=true",
        "--pids-limit", "32", "--cpus", "1.0",
        "--memory", "128m", "--memory-swap", "128m",
        "--tmpfs", "/work:rw,noexec,nosuid,nodev,size=16m,mode=700",
        "--ulimit", "nofile=64:64", "--ulimit", "fsize=1048576:1048576",
        "--ulimit", "nproc=32:32", "--pull", "never",
        "--log-driver", "none", "--restart", "no", "-i", self.image,
    ]
```

Create, attach/start with framed stdin, enforce wall timeout, inspect OOM/exit state,
decode one frame, and always issue explicit `docker rm --force --volumes <name>` in
`finally`. `cancel()` locates only the exact validated label/name and removes it.

- [ ] **Step 4: Implement signed internal FastAPI service**

Create exactly two routes:

```python
@app.post("/internal/v1/executions", response_model=SandboxExecutionResponse)
async def execute(
    request: Request,
    settings: SandboxSettings = Depends(get_sandbox_settings),
    executor: SandboxExecutor = Depends(get_executor),
) -> SandboxExecutionResponse:
    body = await request.body()
    verify_request(
        body,
        method="POST",
        path="/internal/v1/executions",
        headers=dict(request.headers),
        secret=settings.shared_secret,
        now=int(time.time()),
        nonces=request.app.state.nonces,
    )
    execution = SandboxExecutionRequest.model_validate_json(body)
    cached = request.app.state.responses.get(execution.request_id)
    if cached is not None:
        return cached
    result = await run_in_threadpool(executor.execute, execution)
    response = SandboxExecutionResponse(
        protocol_version="1",
        request_id=execution.request_id,
        run_id=execution.run_id,
        result=result,
    )
    request.app.state.responses.put(execution.request_id, response)
    return response


@app.delete("/internal/v1/executions/{run_id}")
async def cancel(
    run_id: str,
    request: Request,
    settings: SandboxSettings = Depends(get_sandbox_settings),
    executor: SandboxExecutor = Depends(get_executor),
) -> dict[str, bool]:
    if re.fullmatch(r"run_[0-9a-f]{32}", run_id) is None:
        raise HTTPException(status_code=404, detail="execution not found")
    body = await request.body()
    verify_request(
        body,
        method="DELETE",
        path=f"/internal/v1/executions/{run_id}",
        headers=dict(request.headers),
        secret=settings.shared_secret,
        now=int(time.time()),
        nonces=request.app.state.nonces,
    )
    removed = await run_in_threadpool(executor.cancel, run_id)
    return {"removed": removed}
```

Middleware rejects bodies over 512 KiB before route handling and maps protocol,
executor, and validation exceptions to redacted internal envelopes. `responses` is a
bounded TTL cache keyed by request ID. Do not expose OpenAPI publicly; bind to the
internal Compose network only.

- [ ] **Step 5: Split runtime and Supervisor images/configuration**

`infra/sandbox-runtime.Dockerfile` copies only standard-library sandbox harness files,
creates UID/GID 65532, sets the fixed entrypoint, and includes no Docker client or
application credentials. `infra/sandbox.Dockerfile` builds the Supervisor with Python,
Docker CLI, and only Supervisor dependencies.

Compose must set the Supervisor to `internal: true`, no `ports`, read-only service
filesystem where compatible, and a Docker Engine connection supplied only to the
Supervisor. Add startup validation for pinned runtime image and a 32-byte secret;
production rejects an unpinned image or insecure executor.

- [ ] **Step 6: Run Green service gates and Compose validation**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider sandbox/tests/test_executor.py `
  sandbox/tests/test_service.py -q
uv run ruff check sandbox backend/app/config.py
uv run mypy sandbox/executor.py sandbox/service.py backend/app/config.py
docker compose config --quiet
```

Expected: all focused tests and Compose validation pass.

- [ ] **Step 7: Commit Supervisor slice**

```powershell
git add -- sandbox infra/sandbox.Dockerfile infra/sandbox-runtime.Dockerfile `
  docker-compose.yml .env.example backend/app/config.py pyproject.toml uv.lock
git commit -m "feat(sandbox): isolate runs with hardened containers"
```

---

### Task 7: Orchestrate Supervisor execution and formal evidence

**Files:**

- Create: `backend/app/sandbox_client.py`
- Create: `backend/app/code_execution.py`
- Create: `backend/tests/test_sandbox_client.py`
- Create: `backend/tests/test_code_execution.py`
- Modify: `backend/app/code_runs.py`

**Interfaces:**

- Consumes: Tasks 1-6 contracts/policies/models/domain/Supervisor.
- Produces: `SandboxClient.execute_phase()/cancel()`, `execute_code_command()`,
  `cancel_code_run()`, and `recover_expired_code_runs()`.

- [ ] **Step 1: Write Red orchestration tests**

With a fake `SandboxClient`, prove transaction boundaries and phase rules:

```python
def test_submit_commits_running_before_external_call(
    db_session, uow_factory, fake_sandbox, submit_command
) -> None:
    fake_sandbox.on_execute = lambda: assert_run_status_in_new_session(
        submit_command.run_id, CodeRunStatus.RUNNING
    )
    view = execute_code_command(
        submit_command, uow_factory=uow_factory, sandbox=fake_sandbox
    )
    assert view.status == CodeRunStatus.COMPLETED


def test_hidden_platform_failure_suppresses_all_assessment_evidence(
    db_session, fake_sandbox, submit_command
) -> None:
    fake_sandbox.visible_result = passing_visible_result()
    fake_sandbox.hidden_result = platform_failure_result("ENGINE_LOST")
    view = execute_code_command(submit_command, sandbox=fake_sandbox)
    assert view.status == CodeRunStatus.PLATFORM_ERROR
    assert view.evidence_event_id is None
```

Also cover visible failure still running hidden, syntax/policy/timeout skipping hidden,
HMAC request headers, client timeout, cancellation, stale recovery, replay, and cleanup.

- [ ] **Step 2: Run orchestration tests Red**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider backend/tests/test_sandbox_client.py `
  backend/tests/test_code_execution.py -q
```

Expected: modules/functions absent.

- [ ] **Step 3: Implement internal client**

`SandboxClient` canonicalizes the exact request, creates timestamp/nonce, signs it,
uses a bounded HTTP timeout, validates the response contract, and maps transport,
auth, schema, and protocol faults to safe platform categories. It never logs request
or response bodies.

- [ ] **Step 4: Implement three-transaction orchestration**

```python
def execute_code_command(command: CodeCommand, *, services: ExecutionServices) -> CodeRunView:
    run = services.reserve(command)          # transaction 1: QUEUED + commit
    services.mark_running(run.id)            # transaction 2: RUNNING + commit
    try:
        visible = services.sandbox.execute_phase(services.visible_request(run.id))
        hidden = None
        if command.mode == CodeRunMode.SUBMIT and should_run_hidden(visible):
            hidden = services.sandbox.execute_phase(services.hidden_request(run.id))
        result = combine_phase_results(visible, hidden, mode=command.mode)
    except SandboxPlatformFailure as exc:
        result = platform_result(run.run_id, exc.category)
    return services.finalize(run.id, result)  # transaction 3: terminal + commit
```

Each service method opens/owns its UoW. `finally` cancellation/cleanup is delegated to
the Supervisor, while any cleanup fault overrides the formal outcome to platform error.

- [ ] **Step 5: Run Green orchestration gates and commit**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider backend/tests/test_sandbox_client.py `
  backend/tests/test_code_execution.py backend/tests/test_code_runs.py -q
uv run ruff check backend/app/sandbox_client.py backend/app/code_execution.py
uv run mypy backend/app/sandbox_client.py backend/app/code_execution.py
git add -- backend/app/sandbox_client.py backend/app/code_execution.py `
  backend/app/code_runs.py backend/tests/test_sandbox_client.py `
  backend/tests/test_code_execution.py
git commit -m "feat(backend): orchestrate isolated code execution"
```

---

### Task 8: Expose student code, submission, cancellation, and hint APIs

**Files:**

- Create: `backend/app/api/code.py`
- Create: `backend/app/api/hints.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/errors.py`
- Create: `backend/tests/test_code_api.py`
- Modify: `packages/api-client/openapi.json`
- Modify: `packages/api-client/src/generated/types.gen.ts`
- Modify: `packages/api-client/src/generated/client.gen.ts`
- Modify: `packages/api-client/src/generated/index.ts`

**Interfaces:**

- Consumes: Task 7 orchestration and Task 1 wire models.
- Produces: five student-scoped APIs and a fresh generated TypeScript client.

- [ ] **Step 1: Write Red API tests**

Cover all five routes, including:

```python
def test_submission_is_idempotent_and_evidence_is_consumable(
    client, db_session, student_auth, active_task, fake_sandbox
) -> None:
    headers = authenticated_headers(student_auth, key="submission-001")
    body = {
        "task_instance_id": str(active_task.id),
        "source_code": "def solve(values): return sum(values)",
        "expected_task_version": active_task.version,
    }
    first = client.post("/api/v1/code/submissions", json=body, headers=headers)
    replay = client.post("/api/v1/code/submissions", json=body, headers=headers)
    assert first.status_code == replay.status_code == 200
    assert first.json()["run_id"] == replay.json()["run_id"]
    evidence_id = first.json()["evidence_event_id"]
    assert evidence_id is not None
    assessment = client.post(
        f"/api/v1/tasks/{active_task.id}/submit",
        json={"evidence_event_id": evidence_id, "expected_task_version": active_task.version},
        headers=authenticated_headers(student_auth, key="formal-submit-001"),
    )
    assert assessment.status_code == 200
```

Add cross-tenant run lookup/cancel denial, missing key, optimistic conflict, concurrent
active run, hidden redaction, platform no-evidence, hint order/budget/replay, audit and
Outbox exactly-once assertions.

- [ ] **Step 2: Run API tests Red**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider backend/tests/test_code_api.py -q
```

Expected: 404s because the routers are not mounted.

- [ ] **Step 3: Implement the five routes**

Mount:

```python
POST /api/v1/code/runs
POST /api/v1/code/submissions
GET  /api/v1/code/runs/{run_id}
POST /api/v1/code/runs/{run_id}/cancel
POST /api/v1/tasks/{task_instance_id}/hints
```

Each write creates a scoped command, checks a cached response first, validates the
task/run/revision within tenant and student scope, invokes the domain/orchestrator,
and returns only the strict view. Register stable mappings for policy/version/active
conflicts, student errors, platform errors, timeout, cancellation, and not-found scope.

- [ ] **Step 4: Run API Green and regenerate OpenAPI**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider backend/tests/test_code_api.py -q
pnpm --filter @pymentor/api-client gen
pnpm typecheck
```

Expected: all API tests pass and OpenAPI contains the five BE-005 paths with no
`unknown` success response.

- [ ] **Step 5: Run affected regression and commit**

```powershell
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider backend/tests/test_learning_api.py `
  backend/tests/test_code_api.py backend/tests/test_contracts_parity.py -q
pnpm contracts:check
git diff --check
git add -- backend/app/api/code.py backend/app/api/hints.py backend/app/main.py `
  backend/app/errors.py backend/tests/test_code_api.py packages/api-client
git commit -m "feat(backend): expose sandbox code evidence APIs"
```

---

### Task 9: Prove real-container isolation and finish BE-005

**Files:**

- Create: `sandbox/tests/test_docker_security.py`
- Modify: `pyproject.toml`
- Modify after verification: sibling sidecar `work-items/backend/BE-005/TASK.md`
- Modify after verification: sibling backend `TRACK.md`

**Interfaces:**

- Consumes: all BE-005 slices and the local Linux Docker Engine.
- Produces: dated isolation evidence, verified BE-005 commit set, and BE-006 READY.

- [ ] **Step 1: Add the Docker marker and image fixture**

Register `docker: requires a real Linux Docker Engine` under pytest markers. A session
fixture checks Linux/server/seccomp/cgroup support, builds the pinned test runtime once,
and removes test-labeled containers in teardown without touching unrelated containers.

- [ ] **Step 2: Write the complete security matrix**

Implement separate real-container tests for:

```text
infinite loop timeout and subsequent recovery
fork/process bomb and PID ceiling
memory exhaustion and OOM classification
stdout/stderr/control-frame flooding
large-file/tmpfs exhaustion
../../ traversal and host-sensitive paths
socket/DNS/network denial
subprocess, dynamic import, ctypes and reflection attempts
reserved instrumentation tamper
non-root child, zero effective capabilities and no-new-privileges
read-only root, no host bind/device/Docker socket
visible/hidden distinct container IDs and hidden API/filesystem absence
result-frame spoof and malformed/trailing output
cleanup after pass/fail/timeout/cancel/protocol error
valid run after each failure class
```

Each test queries only containers labeled with its own run ID and asserts none remain.

- [ ] **Step 3: Build and run real-container security tests**

```powershell
docker build --pull=false -f infra/sandbox-runtime.Dockerfile `
  -t pymentor-sandbox-runtime:be005-test .
$env:PYMENTOR_SANDBOX_RUNTIME_IMAGE = 'pymentor-sandbox-runtime:be005-test'
$env:UV_NO_CACHE = '1'
uv run pytest -p no:cacheprovider -m docker sandbox/tests/test_docker_security.py -q
```

Expected: every security test passes on Linux Docker Engine with seccomp/cgroups; no
skip is allowed for BE-005 completion on this host.

- [ ] **Step 4: Inspect complete requirements/diff**

```powershell
git diff d52a154..HEAD --stat
git diff d52a154..HEAD --check
git status --short
```

Trace every BE-005 task requirement and design section to a contract, constraint,
focused test, or real-container assertion. Fix Critical/Important findings with a new
Red test before verification.

- [ ] **Step 5: Run fresh Python and migration gates**

```powershell
$dbLine = (Select-String -LiteralPath '.env.example' -Pattern '^PYMENTOR_DATABASE_URL=').Line
$env:PYMENTOR_DATABASE_URL = $dbLine.Substring($dbLine.IndexOf('=') + 1).Replace('@localhost:', '@127.0.0.1:') + '?connect_timeout=5'
$env:UV_NO_CACHE = '1'
uv run ruff check --no-cache backend sandbox
uv run mypy --no-incremental backend/app sandbox
uv run pytest -p no:cacheprovider backend/tests sandbox/tests -m "not docker" -q
uv run pytest -p no:cacheprovider -m docker sandbox/tests/test_docker_security.py -q
```

Expected: Ruff/mypy and all Python suites pass; migrations include a successful full
upgrade/downgrade/upgrade.

- [ ] **Step 6: Run contract, client, JS, Compose, and cleanliness gates**

```powershell
pnpm contracts:check
pnpm typecheck
pnpm -r --workspace-concurrency=1 run test
$env:UV_NO_CACHE = '1'
pnpm --filter @pymentor/api-client freshness
docker compose config --quiet
git diff --check
git status --short
```

Expected: all commands exit 0, generated client has no drift, Vitest emits no port
warning, Compose is valid, and the code worktree is clean after the final commit.

- [ ] **Step 7: Commit security evidence code**

```powershell
git add -- sandbox/tests/test_docker_security.py pyproject.toml
git commit -m "test(sandbox): verify BE-005 isolation boundary"
```

- [ ] **Step 8: Mark sidecar IN_REVIEW then DONE**

Record exact commands/results, Docker Engine/runtime evidence, commit SHAs, migration
impact, review findings/fixes, branch/remote/push/PR state, and remaining platform risk.
Move BE-005 through `IN_REVIEW` to `DONE`, set `current_task: BE-006`, and change
BE-006 from `PLANNED` to `READY` without changing lane/worktree.

---

## Plan Self-Review Checklist

- Every design requirement maps to Tasks 1-9.
- Contract names, enum values, routes, table names, transition states, and phase rules
  are consistent across tasks.
- Docker is the only trusted execution path; host execution cannot produce evidence.
- Hidden tests are declarative, server-owned, separately executed, and redacted.
- Database transactions surround state changes but never external execution.
- Platform error suppression is tested in domain, orchestration, API, and Docker layers.
- Migration rollback, client freshness, full tests, and sidecar transition are explicit.
- No implementation step contains an unresolved placeholder or delegates policy choice
  to the implementer.
