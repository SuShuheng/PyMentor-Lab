# BE-004 Deterministic Learning Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic evidence-to-profile-to-path-to-task-to-mastery-to-review loop without allowing Agents to commit formal decisions.

**Architecture:** Normalized PostgreSQL models hold current and immutable historical state. Small FastAPI-side policy services project profiles, validate paths, compile immutable task snapshots, decide mastery, and schedule reviews; API routes wrap writes in the BE-003 UoW with audit, idempotency, and Outbox. Course and knowledge-node IDs remain stable UUID references until BE-009 adds the asset catalogue and foreign keys.

**Tech Stack:** Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16, pytest, TypeScript 5, Zod 3, pnpm, generated OpenAPI client.

## Global Constraints

- Work only on `backend/2026-07-17-pymentor-lab-v1` in `.worktrees/backend/2026-07-17-pymentor-lab-v1`.
- Owned paths are `backend/**`, `packages/contracts/**`, `packages/api-client/**`, and backend-focused tests; do not edit renderer-owned paths.
- Follow Red-Green-Refactor for every behavior and keep formal state plus audit/Outbox in one transaction.
- PostgreSQL is formal-state authority; evidence/audit/history records are append-only.
- Agents may submit proposals but cannot write profiles, paths, tasks, mastery, or reviews directly.
- All IDs are UUIDs; all timestamps are timezone-aware UTC; every formal current-state row has `version`.
- JSONB stores bounded snapshots/metadata only; relational identifiers, versions, scores, states, and timestamps use typed columns.
- All write APIs require `Idempotency-Key`, tenant/student scope validation, stable errors, audit, and Outbox.
- `PASSED_WITH_HELP` cannot unlock all high-order nodes; `INITIAL_MASTERY` requires a review schedule; `STABLE_MASTERY` requires passed delayed-review evidence.
- Migrations must upgrade and downgrade against PostgreSQL 16.

---

### Task 1: Learning-loop persistence and migration

**Files:**

- Create: `backend/app/models/learning.py`
- Create: `backend/migrations/versions/0004_learning_loop.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/tests/test_migrations.py`
- Test: `backend/tests/test_learning_models.py`

**Interfaces:**

- Consumes: `app.db.Base`, identity `Tenant/User`, BE-003 `EvidenceEvent`.
- Produces: ORM enums and models `LearningContext`, `ProfileVersion`,
  `ProfileDimensionScore`, `ProfileChangeProposal`, `ProfileDispute`,
  `LearningPath`, `LearningPathStep`, `TaskDefinition`, `TaskVersion`,
  `TaskInstance`, `TaskStatusHistory`, `AssessmentResult`, `MasteryState`,
  `MasteryStateHistory`, `ReviewSchedule`, and `ReviewAttempt`.

- [ ] **Step 1: Add failing migration structure tests**

Add exact table and constraint assertions:

```python
EXPECTED_0004_TABLES = {
    "learning_contexts", "profile_versions", "profile_dimension_scores",
    "profile_change_proposals", "profile_disputes", "learning_paths",
    "learning_path_steps", "task_definitions", "task_versions",
    "task_instances", "task_status_history", "assessment_results",
    "mastery_states", "mastery_state_history", "review_schedules",
    "review_attempts",
}

def test_migration_0004_creates_learning_loop_tables() -> None:
    cfg = _make_config()
    command.upgrade(cfg, "head")
    from app.db import engine
    assert EXPECTED_0004_TABLES <= set(inspect(engine).get_table_names())

def test_learning_loop_unique_constraints() -> None:
    cfg = _make_config()
    command.upgrade(cfg, "head")
    from app.db import engine
    inspector = inspect(engine)
    assert "uq_profile_student_version" in {
        row["name"] for row in inspector.get_unique_constraints("profile_versions")
    }
    assert "uq_mastery_student_course_node" in {
        row["name"] for row in inspector.get_unique_constraints("mastery_states")
    }
```

- [ ] **Step 2: Run the migration tests and observe Red**

Run:

```powershell
$dbLine = (Select-String -LiteralPath '.env.example' -Pattern '^PYMENTOR_DATABASE_URL=').Line
$env:PYMENTOR_DATABASE_URL = $dbLine.Substring($dbLine.IndexOf('=') + 1).Replace('@localhost:', '@127.0.0.1:') + '?connect_timeout=5'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend/tests/test_migrations.py::test_migration_0004_creates_learning_loop_tables `
  backend/tests/test_migrations.py::test_learning_loop_unique_constraints -q
```

Expected: FAIL because revision `0004` and its tables do not exist.

- [ ] **Step 3: Add the ORM enums and models**

Define stable enums and representative constrained rows; apply the same
column pattern to every model named in the interface:

```python
class MasteryStatus(StrEnum):
    UNSEEN = "UNSEEN"
    LEARNING = "LEARNING"
    PASSED_WITH_HELP = "PASSED_WITH_HELP"
    INITIAL_MASTERY = "INITIAL_MASTERY"
    STABLE_MASTERY = "STABLE_MASTERY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"

class ProfileVersion(Base):
    __tablename__ = "profile_versions"
    __table_args__ = (
        UniqueConstraint("student_id", "version", name="uq_profile_student_version"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

class MasteryState(Base):
    __tablename__ = "mastery_states"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "course_id", "node_id",
            name="uq_mastery_student_course_node",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    student_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    course_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    node_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    status: Mapped[MasteryStatus] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
```

Use check constraints for `score/confidence/independence_score/transfer_score`
in `0..1`, `support_level` in `0..3`, non-negative `daily_minutes`, positive
path positions, and timezone-aware due timestamps. Add a partial unique index
on active task instances using `(student_id, task_version_id, active_key)`.

- [ ] **Step 4: Add Alembic revision `0004_learning_loop`**

Create the tables in dependency order and downgrade them in exact reverse
order. The revision header is:

```python
revision: str = "0004"
down_revision: str = "0003"
```

The active-task index must be PostgreSQL partial SQL:

```python
op.create_index(
    "uq_task_instance_active",
    "task_instances",
    ["student_id", "task_version_id", "active_key"],
    unique=True,
    postgresql_where=sa.text("status = 'ACTIVE'"),
)
```

- [ ] **Step 5: Run migration and model tests Green**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend/tests/test_migrations.py backend/tests/test_learning_models.py -q
```

Expected: all tests pass, including `upgrade head -> downgrade base -> upgrade head`.

- [ ] **Step 6: Commit the persistence slice**

```powershell
git add backend/app/models backend/migrations/versions/0004_learning_loop.py `
  backend/tests/test_migrations.py backend/tests/test_learning_models.py
git commit -m "feat(backend): add BE-004 learning-loop persistence"
```

---

### Task 2: Shared learning-loop contracts

**Files:**

- Create: `backend/app/contracts/learning.py`
- Create: `packages/contracts/src/learning.ts`
- Modify: `backend/app/contracts/__init__.py`
- Modify: `packages/contracts/src/index.ts`
- Modify: `packages/contracts/src/export-json-schema.ts`
- Modify: `packages/contracts/src/conformance.ts`
- Modify: `backend/tests/test_contracts_parity.py`

**Interfaces:**

- Consumes: ORM enum string values from Task 1.
- Produces: `ProfileSnapshot`, `ProfileDisputeRequest`, `PathSnapshot`,
  `TodayItem`, `TaskStartResponse`, `AssessmentSubmission`, `MasteryView`,
  `ReviewView`, and `ReviewRescheduleRequest` in Pydantic and Zod.

- [ ] **Step 1: Add shared fixtures and parity registrations first**

Add fixtures such as:

```python
"MasteryView": [{
    "id": "00000000-0000-0000-0000-000000000031",
    "course_id": "00000000-0000-0000-0000-000000000032",
    "node_id": "00000000-0000-0000-0000-000000000033",
    "status": "INITIAL_MASTERY",
    "version": 2,
    "review_due_at": "2026-07-24T00:00:00Z",
}],
"ReviewRescheduleRequest": [{"due_at": "2026-07-25T00:00:00Z"}],
```

Register every new model in `MODEL_BY_NAME` and mirror the same fixtures in
`packages/contracts/src/conformance.ts`.

- [ ] **Step 2: Run contracts Red**

```powershell
pnpm contracts:check
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend/tests/test_contracts_parity.py -q
```

Expected: FAIL because the new Pydantic/Zod models and schema exports do not exist.

- [ ] **Step 3: Implement matching Pydantic and Zod schemas**

Use strict enums and matching nullable semantics:

```python
class MasteryView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    status: MasteryStatusContract
    version: int = Field(ge=1)
    review_due_at: str | None = None
```

```typescript
export const MasteryView = z.object({
  id: z.string().min(1),
  course_id: z.string().min(1),
  node_id: z.string().min(1),
  status: MasteryStatus,
  version: z.number().int().min(1),
  review_due_at: z.string().nullish(),
});
```

- [ ] **Step 4: Export schemas and run parity Green**

```powershell
pnpm contracts:check
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend/tests/test_contracts_parity.py -q
pnpm -r run typecheck
```

Expected: Pydantic and Zod accept the same fixtures and expose identical fields.

- [ ] **Step 5: Commit the contract slice**

```powershell
git add backend/app/contracts backend/tests/test_contracts_parity.py `
  packages/contracts
git commit -m "feat(backend): add BE-004 learning-loop contracts"
```

---

### Task 3: Evidence-driven profile projection

**Files:**

- Create: `backend/app/profile_projection.py`
- Test: `backend/tests/test_profile_projection.py`

**Interfaces:**

- Consumes: `EvidenceEvent`, Task 1 profile models, `SqlAlchemyUnitOfWork`.
- Produces:
  `project_profile(db, *, tenant_id, student_id, source_event_id,
  expected_version, updates) -> ProfileVersion` and
  `create_profile_dispute(db, *, tenant_id, student_id, profile_version_id,
  reason) -> ProfileDispute`.

- [ ] **Step 1: Write Red tests for first projection, conflict, and bounds**

```python
def test_profile_projection_versions_monotonically(db_session, student) -> None:
    first = project_profile(
        db_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        source_event_id="evt_profile_1",
        expected_version=0,
        updates=[DimensionUpdate(
            dimension="DEBUGGING",
            scope_key="loops",
            score=0.45,
            confidence=0.8,
            support_level=2,
        )],
    )
    second = project_profile(
        db_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        source_event_id="evt_profile_2",
        expected_version=1,
        updates=[DimensionUpdate(
            dimension="DEBUGGING",
            scope_key="loops",
            score=0.65,
            confidence=0.9,
            support_level=1,
        )],
    )
    assert (first.version, second.version) == (1, 2)

def test_profile_projection_rejects_stale_version(db_session, student) -> None:
    with pytest.raises(ProfileVersionConflict):
        project_profile(
            db_session,
            tenant_id=student.tenant_id,
            student_id=student.id,
            source_event_id="evt_stale",
            expected_version=0,
            updates=[DimensionUpdate(
                dimension="DEBUGGING",
                scope_key="loops",
                score=0.7,
                confidence=0.9,
                support_level=1,
            )],
        )
```

- [ ] **Step 2: Run profile tests Red**

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend/tests/test_profile_projection.py -q
```

Expected: collection or assertion failure because the projector is absent.

- [ ] **Step 3: Implement the minimal projector**

Use a row lock for the current profile header and create immutable copies:

```python
class ProfileVersionConflict(Exception):
    pass

def project_profile(
    db: Session,
    *,
    tenant_id: UUID,
    student_id: UUID,
    source_event_id: str,
    expected_version: int,
    updates: list[DimensionUpdate],
) -> ProfileVersion:
    current = db.scalar(
        select(ProfileVersion)
        .where(ProfileVersion.student_id == student_id)
        .order_by(ProfileVersion.version.desc())
        .limit(1)
        .with_for_update()
    )
    actual = current.version if current else 0
    if actual != expected_version:
        raise ProfileVersionConflict(f"expected {expected_version}, actual {actual}")
    version = ProfileVersion(
        tenant_id=tenant_id,
        student_id=student_id,
        version=actual + 1,
        source_event_id=source_event_id,
    )
    db.add(version)
    db.flush()
    for update in updates:
        db.add(ProfileDimensionScore(profile_version_id=version.id, **asdict(update)))
    db.flush()
    return version
```

Validate dimension names, score/confidence bounds, and support level before
writing. A dispute references an existing same-student profile version and is
append-only.

- [ ] **Step 4: Run profile tests Green and refactor duplicate score-copy code**

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend/tests/test_profile_projection.py -q
```

Expected: version, conflict, scope, dispute, and dimension-bound tests pass.

- [ ] **Step 5: Commit the profile slice**

```powershell
git add backend/app/profile_projection.py backend/tests/test_profile_projection.py
git commit -m "feat(backend): project versioned learning profiles"
```

---

### Task 4: Path validator and persistence

**Files:**

- Create: `backend/app/pathing.py`
- Test: `backend/tests/test_pathing.py`

**Interfaces:**

- Consumes: Task 1 path/mastery/review models.
- Produces:
  `validate_path(proposal: PathProposal, context: ValidationContext) -> ValidatedPath`
  and `persist_validated_path(db, *, tenant_id, student_id, course_id,
  expected_version, validated) -> LearningPath`.

- [ ] **Step 1: Write Red policy tests**

```python
def test_due_review_precedes_new_learning() -> None:
    result = validate_path(
        PathProposal(steps=[StepProposal(node_id=NEW_NODE, estimated_minutes=20)]),
        ValidationContext(
            daily_minutes=30,
            prerequisites={},
            completed_nodes=set(),
            due_reviews=[DueReview(review_id=REVIEW_ID, node_id=OLD_NODE)],
            mastery_policy_nodes={NEW_NODE, OLD_NODE},
            resource_ready_nodes={NEW_NODE, OLD_NODE},
            active_node_ids=set(),
        ),
    )
    assert result.steps[0].kind == "REVIEW"

def test_validator_inserts_prerequisite_and_splits_time() -> None:
    result = validate_path(
        PathProposal(steps=[StepProposal(
            node_id=TARGET,
            estimated_minutes=75,
            kind="LEARN",
            scenario_key="loops-long",
        )]),
        ValidationContext(
            daily_minutes=30,
            prerequisites={TARGET: (PREREQ,)},
            completed_nodes=set(),
            due_reviews=[],
            mastery_policy_nodes={TARGET, PREREQ},
            resource_ready_nodes={TARGET, PREREQ},
            active_node_ids=set(),
        ),
    )
    assert [step.node_id for step in result.steps[:2]] == [PREREQ, TARGET]
    assert all(step.estimated_minutes <= 30 for step in result.steps)
```

Add separate tests for missing mastery policy, missing resources, duplicate
active work becoming a variant, forbidden node state, and platform error not
creating remediation.

- [ ] **Step 2: Run path tests Red**

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend/tests/test_pathing.py -q
```

Expected: FAIL because `validate_path` is absent.

- [ ] **Step 3: Implement pure policy dataclasses and validator**

```python
@dataclass(frozen=True)
class ValidationFinding:
    code: str
    node_id: UUID | None
    repaired: bool

@dataclass(frozen=True)
class ValidatedPath:
    steps: tuple[ValidatedStep, ...]
    findings: tuple[ValidationFinding, ...]

def validate_path(proposal: PathProposal, context: ValidationContext) -> ValidatedPath:
    steps: list[ValidatedStep] = _due_review_steps(context.due_reviews)
    findings: list[ValidationFinding] = []
    for proposed in proposal.steps:
        steps.extend(_missing_prerequisites(proposed, context, findings))
        steps.extend(_validate_and_split(proposed, context, findings))
    return ValidatedPath(tuple(_deduplicate(steps, context, findings)), tuple(findings))
```

Keep validation pure; persistence accepts only `ValidatedPath` and marks the
previous current path `SUPERSEDED` in the same transaction.

- [ ] **Step 4: Run path tests Green**

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend/tests/test_pathing.py -q
```

Expected: every frozen §9.1/§9.2 rule has a passing focused test.

- [ ] **Step 5: Commit the path slice**

```powershell
git add backend/app/pathing.py backend/tests/test_pathing.py
git commit -m "feat(backend): validate deterministic learning paths"
```

---

### Task 5: Immutable task compiler and instances

**Files:**

- Create: `backend/app/task_compiler.py`
- Test: `backend/tests/test_task_compiler.py`

**Interfaces:**

- Consumes: validated path steps and Task 1 task models.
- Produces:
  `compile_task_version(db, definition, compile_input) -> TaskVersion` and
  `start_task_instance(db, *, student_id, task_version_id, active_key) -> TaskInstance`.

- [ ] **Step 1: Write Red immutability and active-key tests**

```python
def test_started_instance_keeps_original_snapshot(db_session, student) -> None:
    version = compile_task_version(db_session, definition, CompileInput(
        prompt="Fix the loop boundary",
        tests_policy={"hidden": ["upper_bound"]},
        hint_policy={"max_level": 2},
        mastery_policy={"independence_min": 0.7},
        scenario_key="range-stop-v1",
    ))
    instance = start_task_instance(
        db_session, student_id=student.id,
        task_version_id=version.id, active_key="today",
    )
    definition.title = "Changed later"
    db_session.flush()
    assert instance.snapshot["prompt"] == "Fix the loop boundary"

def test_active_instance_is_replay_safe(db_session, student) -> None:
    first = start_task_instance(
        db_session,
        student_id=student.id,
        task_version_id=published_version.id,
        active_key="today",
    )
    second = start_task_instance(
        db_session,
        student_id=student.id,
        task_version_id=published_version.id,
        active_key="today",
    )
    assert second.id == first.id
```

- [ ] **Step 2: Run task tests Red**

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend/tests/test_task_compiler.py -q
```

Expected: FAIL because compiler/start services do not exist.

- [ ] **Step 3: Implement canonical snapshot hashing and start logic**

```python
def _canonical_snapshot(data: dict[str, Any]) -> tuple[dict[str, Any], str]:
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.loads(encoded), hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def start_task_instance(
    db: Session,
    *,
    student_id: UUID,
    task_version_id: UUID,
    active_key: str,
) -> TaskInstance:
    existing = db.scalar(select(TaskInstance).where(
        TaskInstance.student_id == student_id,
        TaskInstance.task_version_id == task_version_id,
        TaskInstance.active_key == active_key,
        TaskInstance.status == TaskInstanceStatus.ACTIVE,
    ))
    if existing:
        return existing
    version = db.get(TaskVersion, task_version_id)
    if version is None or not version.published:
        raise TaskVersionUnavailable
    instance = TaskInstance(
        student_id=student_id,
        task_version_id=version.id,
        active_key=active_key,
        status=TaskInstanceStatus.ACTIVE,
        snapshot=copy.deepcopy(version.snapshot),
        snapshot_digest=version.snapshot_digest,
    )
    db.add(instance)
    db.flush()
    return instance
```

Do not expose an update function for task-version or instance snapshots.

- [ ] **Step 4: Run task tests Green**

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend/tests/test_task_compiler.py -q
```

Expected: deterministic digest, replay, unique active key, and immutability tests pass.

- [ ] **Step 5: Commit the task slice**

```powershell
git add backend/app/task_compiler.py backend/tests/test_task_compiler.py
git commit -m "feat(backend): compile immutable task snapshots"
```

---

### Task 6: Assessment, mastery, and delayed reviews

**Files:**

- Create: `backend/app/mastery.py`
- Create: `backend/app/reviews.py`
- Test: `backend/tests/test_mastery.py`
- Test: `backend/tests/test_reviews.py`

**Interfaces:**

- Consumes: Task 1 assessment/mastery/review models, BE-003 evidence IDs.
- Produces:
  `record_assessment_and_decide(db, facts, *, policy, tenant_id, student_id,
  course_id, node_id, evidence_event_id, now) -> MasteryDecision`,
  `mark_due_reviews(db, *, now) -> list[ReviewSchedule]`,
  `reschedule_review(db, *, review_id, requested_due_at, now) -> ReviewSchedule`,
  and `complete_review(db, *, review_id, facts, evidence_event_id, now)
  -> MasteryState`.

- [ ] **Step 1: Write Red mastery-transition tests**

```python
def test_helped_pass_does_not_become_initial_mastery(db_session, student) -> None:
    decision = record_assessment_and_decide(
        db_session,
        AssessmentFacts(correct=True, hidden_tests_passed=True, hints_used=2,
                        support_level=2, independence_score=0.45,
                        transfer_score=0.8, platform_error=False),
        policy=MasteryPolicy(independence_min=0.7, transfer_min=0.6,
                             max_hints_for_mastery=1, review_delay_days=7),
        tenant_id=student.tenant_id,
        student_id=student.id, course_id=COURSE_ID, node_id=NODE_ID,
        evidence_event_id="evt_assessment_helped",
        now=datetime(2026, 7, 17, tzinfo=UTC),
    )
    assert decision.state.status == MasteryStatus.PASSED_WITH_HELP
    assert decision.review is None

def test_initial_mastery_creates_review_atomically(db_session, student) -> None:
    decision = record_assessment_and_decide(
        db_session,
        AssessmentFacts(
            correct=True,
            hidden_tests_passed=True,
            hints_used=0,
            support_level=0,
            independence_score=0.9,
            transfer_score=0.8,
            platform_error=False,
        ),
        policy=MasteryPolicy(
            independence_min=0.7,
            transfer_min=0.6,
            max_hints_for_mastery=1,
            review_delay_days=7,
        ),
        tenant_id=student.tenant_id,
        student_id=student.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        evidence_event_id="evt_initial",
        now=datetime(2026, 7, 17, tzinfo=UTC),
    )
    assert decision.state.status == MasteryStatus.INITIAL_MASTERY
    assert decision.review.status == ReviewStatus.SCHEDULED
```

Add illegal-transition tests and ensure platform errors create neither mastery
loss nor remedial review.

- [ ] **Step 2: Write Red real-time review tests**

```python
def test_due_review_uses_persisted_utc_timestamp(db_session, scheduled_review) -> None:
    before = mark_due_reviews(db_session, now=scheduled_review.due_at - timedelta(seconds=1))
    due = mark_due_reviews(db_session, now=scheduled_review.due_at)
    assert before == []
    assert [item.id for item in due] == [scheduled_review.id]

def test_postpone_never_reduces_mastery(db_session, initial_mastery, scheduled_review) -> None:
    reschedule_review(
        db_session, review_id=scheduled_review.id,
        requested_due_at=scheduled_review.due_at + timedelta(days=2),
        now=scheduled_review.due_at - timedelta(days=1),
    )
    assert initial_mastery.status == MasteryStatus.INITIAL_MASTERY
```

Add tests that stable mastery requires a new-scenario, unassisted, passed review
with evidence newer than initial mastery; failed reviews return to
`REVIEW_REQUIRED` and schedule another variant.

- [ ] **Step 3: Run mastery/review tests Red**

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend/tests/test_mastery.py backend/tests/test_reviews.py -q
```

Expected: FAIL because the policy services do not exist.

- [ ] **Step 4: Implement the transition table and review clock functions**

```python
ALLOWED_TRANSITIONS = {
    MasteryStatus.UNSEEN: {MasteryStatus.LEARNING},
    MasteryStatus.LEARNING: {
        MasteryStatus.PASSED_WITH_HELP, MasteryStatus.INITIAL_MASTERY,
    },
    MasteryStatus.PASSED_WITH_HELP: {
        MasteryStatus.INITIAL_MASTERY, MasteryStatus.REVIEW_REQUIRED,
    },
    MasteryStatus.INITIAL_MASTERY: {
        MasteryStatus.REVIEW_REQUIRED, MasteryStatus.STABLE_MASTERY,
    },
    MasteryStatus.REVIEW_REQUIRED: {
        MasteryStatus.INITIAL_MASTERY, MasteryStatus.STABLE_MASTERY,
    },
    MasteryStatus.STABLE_MASTERY: {MasteryStatus.REVIEW_REQUIRED},
}

def mark_due_reviews(db: Session, *, now: datetime) -> list[ReviewSchedule]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    reviews = list(db.scalars(select(ReviewSchedule).where(
        ReviewSchedule.status == ReviewStatus.SCHEDULED,
        ReviewSchedule.due_at <= now,
    ).with_for_update(skip_locked=True)))
    for review in reviews:
        review.status = ReviewStatus.DUE
    db.flush()
    return reviews
```

The decision function appends `MasteryStateHistory`; initial mastery creates a
review before returning; review completion checks scenario, hint ceiling,
evidence timestamp, and platform-error separation.

- [ ] **Step 5: Run mastery/review tests Green**

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend/tests/test_mastery.py backend/tests/test_reviews.py -q
```

Expected: all legal, illegal, due, postpone, failure, and stable-mastery cases pass.

- [ ] **Step 6: Commit the mastery/review slice**

```powershell
git add backend/app/mastery.py backend/app/reviews.py `
  backend/tests/test_mastery.py backend/tests/test_reviews.py
git commit -m "feat(backend): decide mastery and schedule delayed reviews"
```

---

### Task 7: Student learning-loop APIs with UoW, idempotency, audit, and Outbox

**Files:**

- Create: `backend/app/api/profiles.py`
- Create: `backend/app/api/learning.py`
- Create: `backend/app/api/paths.py`
- Create: `backend/app/api/tasks.py`
- Create: `backend/app/api/mastery.py`
- Create: `backend/app/api/reviews.py`
- Create: `backend/app/command_idempotency.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/errors.py`
- Test: `backend/tests/test_learning_api.py`

**Interfaces:**

- Consumes: Tasks 2-6 contracts/services and BE-003 UoW/idempotency/audit/Outbox.
- Produces these nine endpoints:
  `GET /api/v1/profiles/current`, `GET /api/v1/learning/today`,
  `GET /api/v1/paths/current`, `GET /api/v1/mastery`,
  `GET /api/v1/reviews/due`, `POST /api/v1/profiles/disputes`,
  `POST /api/v1/tasks/{task_version_id}/start`,
  `POST /api/v1/tasks/{task_instance_id}/submit`, and
  `POST /api/v1/reviews/{review_id}/reschedule`.

- [ ] **Step 1: Write Red API tests for scope and reads**

```python
def test_current_profile_is_student_scoped(client, student_token, other_profile) -> None:
    response = client.get(
        "/api/v1/profiles/current",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert response.status_code == 200
    assert response.json()["student_id"] != str(other_profile.student_id)

def test_today_prioritizes_due_review(client, student_token, due_review, path_step) -> None:
    response = client.get(
        "/api/v1/learning/today",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert response.json()[0]["kind"] == "REVIEW"
```

- [ ] **Step 2: Write Red write-command tests**

```python
def test_task_start_replay_returns_same_instance(client, student_token, task_version) -> None:
    headers = {
        "Authorization": f"Bearer {student_token}",
        "Idempotency-Key": "start-task-001",
        "x-trace-id": "trc_start_task",
    }
    first = client.post(f"/api/v1/tasks/{task_version.id}/start", headers=headers)
    second = client.post(f"/api/v1/tasks/{task_version.id}/start", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

def test_write_command_commits_audit_and_outbox(
    client, db_session, student_token, task_version
) -> None:
    response = client.post(
        f"/api/v1/tasks/{task_version.id}/start",
        headers={
            "Authorization": f"Bearer {student_token}",
            "Idempotency-Key": "cmd-001",
            "x-trace-id": "trc_cmd_1",
        },
    )
    assert response.status_code == 200
    assert db_session.scalar(select(AuditEvent).where(
        AuditEvent.trace_id == "trc_cmd_1")) is not None
    assert db_session.scalar(select(OutboxEvent).where(
        OutboxEvent.trace_id == "trc_cmd_1")) is not None
```

Add tests for missing key (`VALIDATION_ERROR`), stale profile version
(`CONFLICT`), cross-tenant object denial, review postpone, task submission, and
pending idempotency conflict.

- [ ] **Step 3: Run API tests Red**

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend/tests/test_learning_api.py -q
```

Expected: 404/collection failures because routers and command adapter are absent.

- [ ] **Step 4: Implement the idempotent command adapter**

```python
@dataclass(frozen=True)
class CommandScope:
    tenant_id: UUID
    user_id: UUID
    endpoint: str
    key: str

def require_idempotency_key(request: Request) -> str:
    key = extract_idempotency_key(request)
    if key is None or not 1 <= len(key) <= 128:
        raise HTTPException(status_code=422, detail="valid Idempotency-Key required")
    return key

def begin_command(db: Session, scope: CommandScope) -> IdempotencyKey | None:
    return get_or_create_idempotency(
        db, key=scope.key, tenant_id=scope.tenant_id,
        user_id=scope.user_id, endpoint=scope.endpoint,
    )
```

Map `IdempotencyScopeConflictError`, in-progress reservations, and
`ProfileVersionConflict` to HTTP 409 so the existing stable handler emits
`CONFLICT`.

- [ ] **Step 5: Implement routers and atomic write handlers**

Every write handler follows this exact pattern:

```python
with SqlAlchemyUnitOfWork(accept_session=db) as uow:
    cached = begin_command(db, scope)
    if cached is not None and cached.response_status is not None:
        return JSONResponse(cached.response_body, status_code=cached.response_status)
    result = start_task_instance(
        db,
        student_id=user.id,
        task_version_id=task_version_id,
        active_key="today",
    )
    record_audit(db, tenant_id=user.tenant_id, actor_user_id=user.id,
                 action="TASK_STARTED", resource_type="task_instance",
                 resource_id=str(result.id), trace_id=request.state.trace_id)
    uow.publish(event_type="TASK_STARTED", aggregate_type="task_instance",
                aggregate_id=str(result.id), tenant_id=user.tenant_id,
                trace_id=request.state.trace_id)
    body = TaskStartResponse.model_validate(result_to_wire(result)).model_dump(mode="json")
    save_response(db, key=scope.key, response_status=200, response_body=body)
    uow.commit()
return body
```

Reads always filter `tenant_id=user.tenant_id` and `student_id=user.id` before
looking up resource IDs.

- [ ] **Step 6: Run API tests Green and regenerate OpenAPI**

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend/tests/test_learning_api.py -q
$env:UV_NO_CACHE = '1'
pnpm --filter @pymentor/api-client gen
pnpm -r run typecheck
```

Expected: API tests pass and generated client exposes the nine BE-004 endpoints.

- [ ] **Step 7: Commit the API slice**

```powershell
git add backend/app/api backend/app/command_idempotency.py backend/app/main.py `
  backend/app/errors.py backend/tests/test_learning_api.py packages/api-client
git commit -m "feat(backend): expose BE-004 learning-loop APIs"
```

---

### Task 8: BE-004 review, full verification, and sidecar completion

**Files:**

- Modify after verification: sibling sidecar `work-items/backend/BE-004/TASK.md`
- Modify after verification: sibling sidecar backend `TRACK.md`

**Interfaces:**

- Consumes: all BE-004 slices.
- Produces: verified BE-004 commit set and `BE-005` READY handoff state.

- [ ] **Step 1: Inspect the complete BE-004 diff and requirements**

```powershell
git diff 3ea07ee..HEAD --stat
git diff 3ea07ee..HEAD --check
git status --short
```

Review every design requirement against a test, migration constraint, route,
or contract artifact. Fix Critical/Important findings with new focused Red tests.

- [ ] **Step 2: Run fresh Python gates**

```powershell
$dbLine = (Select-String -LiteralPath '.env.example' -Pattern '^PYMENTOR_DATABASE_URL=').Line
$env:PYMENTOR_DATABASE_URL = $dbLine.Substring($dbLine.IndexOf('=') + 1).Replace('@localhost:', '@127.0.0.1:') + '?connect_timeout=5'
.\.venv\Scripts\ruff.exe check --no-cache backend
.\.venv\Scripts\mypy.exe --no-incremental backend/app
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend/tests -q
```

Expected: Ruff/mypy exit 0 and all backend tests pass, including full migration round-trip.

- [ ] **Step 3: Run fresh contract/client/JS gates**

```powershell
pnpm contracts:check
pnpm -r run typecheck
pnpm -r --workspace-concurrency=1 run test
$env:UV_NO_CACHE = '1'
pnpm --filter @pymentor/api-client freshness
docker compose config --quiet
git diff --check
```

Expected: all commands exit 0; Vitest output contains no port warning;
freshness reports no generated diff.

- [ ] **Step 4: Mark BE-004 IN_REVIEW then DONE with evidence**

Record exact command results, review findings/fixes, commit SHAs, branch, remote
state, push/PR result, migration impact, and remaining platform risk. Move the
track row `BE-004` through `IN_REVIEW` to `DONE`, set `current_task: BE-005`,
and set `BE-005/TASK.md` to `READY` without changing lane or worktree.

- [ ] **Step 5: Confirm clean code worktree**

```powershell
git status --short
git log -8 --oneline
```

Expected: no code-worktree changes and the BE-004 slice commits are visible.
