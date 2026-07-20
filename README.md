# PyMentor Lab

> A higher-education **Python learning system** that turns student interaction
> into durable learning evidence, an eight-dimensional profile, a validated
> personalized path, executable tasks, five resource types, assessment, mastery
> decisions, and delayed review — where an **LLM never directly decides formal
> mastery**. Real multi-agent collaboration is paired with deterministic
> domain engines so every high-stakes outcome is explainable and replayable.

[![Status](https://img.shields.io/badge/status-V1.0%20competition%20release%20(NOT%20READY)-orange)](docs/verification/release/v1.0-gap-report.md)
[![License](https://img.shields.io/badge/license-Proprietary%20(All%20Rights%20Reserved)-red)](#license)
[![Node](https://img.shields.io/badge/node-%E2%89%A5%2020%20LTS-green)](https://nodejs.org/)
[![Python](https://img.shields.io/badge/python-%E2%89%A5%203.13-blue)](https://www.python.org/)
[![pnpm](https://img.shields.io/badge/pnpm-11-f69220)](https://pnpm.io/)

---

## ✨ Highlights

- **Evidence-first learning loop** — every interaction is persisted as learning
  evidence and projected into an eight-dimensional competency profile.
- **LLM stays out of the gradebook** — deterministic engines own mastery
  decisions, paths, and snapshots; the LLM only proposes and drafts, never
  finalizes. Every high-stakes outcome is explainable.
- **Six-node LangGraph agent** — orchestrates profiling, path validation, task
  compilation, resource generation, assessment, and delayed review.
- **Five core resource types** generated per validated task.
- **Isolated Python sandbox** for real student-code execution with tracing.
- **14 chapters / 93 knowledge nodes** seed (exceeds the 80+ target).
- **Deterministic contracts** — Pydantic ↔ Zod conformance gate is a frozen
  boundary between Python services and the TypeScript agent/UI.
- **Cross-platform monorepo** — FastAPI + LangGraph.js + Electron + Docker, one
  `docker compose up --build` to start everything.

## ⚠️ Release status

**V1.0 (competition release) is merged but NOT READY for production.**

Per [`docs/verification/release/v1.0-gap-report.md`](docs/verification/release/v1.0-gap-report.md):

- ✅ **M0–M2 achieved** — backend deterministic engines + integration
  (sandbox, mastery, re-test, registration approval, six-agent orchestration,
  five resources, SSE, replay, progressive release).
- ⚠️ **M3 / M4 partial** — admin ops/health/audit/agent-replay shipped; TTS &
  captions, full Provider CRUD UI, and the 7-minute demo recording are
  outstanding.
- ❌ **Frontend P0 layer not complete.**

Follow-on work is tracked under the `2026-07-19-pymentor-lab-v1.1` workstream
(FE-012..026, BE-017..030, INT-008..012).

## 🧱 Monorepo layout

```
apps/web/               Student UI (Vite + React + TS)
apps/admin/             Admin UI (Vite + React + Tailwind)
apps/desktop/           Electron main / preload / renderer shell
backend/                FastAPI: API, deterministic domain, auth, RBAC, Outbox
workers/agent-worker/   LangGraph.js: six-agent orchestration + resources
sandbox/                Isolated Python student-code runner with tracing
packages/contracts/     Shared schemas: Pydantic ↔ Zod (frozen boundary)
packages/api-client/    Generated OpenAPI TypeScript SDK (committed, freshness-gated)
packages/ui/            Shared React component library
packages/charts/        Shared chart components
packages/config/        Shared TS build config
knowledge/              Course knowledge assets (14 chapters / 93 nodes)
infra/                  Infrastructure configuration
docs/                   Design docs + verification evidence
scripts/                Operational scripts (e.g. knowledge asset generation)
compose/                Deployment-kit build scripts (build-dist.mjs, bootstrapper.iss)
tests/                  Cross-application E2E (Playwright)
docker-compose.yml      One-command local start
```

> `raw/` (gitignored) holds competition & design inputs — **not runtime code**.

## 🏛️ Architecture at a glance

```
 Student ─► apps/web ─► backend (FastAPI)
   │                         │
   │                         ├─► deterministic domain (mastery, path, snapshots)
   │                         ├─► Outbox ─► Redis stream ─► agent-worker
   │                         └─► sandbox (isolated Python execution)
   │                                                ▲
   └─ apps/desktop (Electron) ──────────────────────┘ shared @pymentor/contracts
```

- **PostgreSQL** — durable state, identity, RBAC, learning evidence.
- **Redis** — BullMQ jobs + the API-owned transactional agent-event stream.
- **MinIO** — object storage for resources & artifacts.
- **agent-worker** — LangGraph.js, six nodes, Redis checkpointed.
- **sandbox** — Python 3.13, policy-gated execution with tracing.
- **contracts** — single source of truth; `pnpm contracts:check` is a merge gate.

## 🚀 Quick start

> **Requires:** Node ≥ 20 LTS, pnpm 11, Python 3.13, `uv`, Docker.

```bash
# 1. JavaScript workspace
pnpm install

# 2. Python toolchain (uv fetches the 3.13 interpreter)
uv venv -p 3.13
uv pip install -e ".[dev]"

# 3. Configure local environment
cp .env.example .env        # then edit secrets/keys as documented inside

# 4. Start everything (PostgreSQL, Redis, MinIO, API, Worker, Sandbox)
docker compose up --build
```

See [`compose/README.md`](compose/README.md) for the Windows deployment-kit
build (`compose_mee.bat` → self-contained installer via Inno Setup).

## 🛠️ Commands

| Command | Purpose |
|---|---|
| `pnpm lint && pnpm test` | TypeScript lint + Vitest suites (recursive) |
| `pnpm typecheck` | Recursive TypeScript type-check |
| `pnpm contracts:check` | Pydantic ↔ Zod conformance gate (merge gate) |
| `pnpm contracts:gen` | Regenerate the OpenAPI TypeScript SDK |
| `uv run ruff check && uv run mypy backend sandbox` | Python lint + types |
| `uv run pytest backend/tests` | FastAPI / domain tests |
| `docker compose up --build` | Start the full local stack |
| `.\scripts\generate_knowledge_assets.py` | Regenerate the course bundle + JSON Schema |

## 🧪 Testing

- **Vitest** — frontend / worker units (`*.test.ts(x)`).
- **pytest** — backend / sandbox tests (`test_*.py`).
- **Playwright** — cross-application E2E under `tests/`.
- Contract changes require **Pydantic ↔ Zod conformance coverage**.

We follow Red-Green-Refactor for behavior changes; every fix ships a focused
regression test.

## 📚 Documentation

- [`AGENTS.md`](AGENTS.md) — repository guidelines for contributors & agents.
- [`docs/`](docs/) — design documents and verification evidence.
- [`docs/verification/release/v1.0-gap-report.md`](docs/verification/release/v1.0-gap-report.md) — V1.0 design-vs-implementation gap report.
- [`docs/verification/release/sbom.cdx.json`](docs/verification/release/sbom.cdx.json) — CycloneDX SBOM.
- [`knowledge/python-general/README.md`](knowledge/python-general/README.md) — course asset (14 chapters / 93 nodes) and regeneration.
- [`.env.example`](.env.example) — annotated local environment template.

## 🗺️ Roadmap

- **V1.1** — close the V1.0 gap: frontend P0 layer, TTS & captions, Provider
  CRUD UI, admin advanced charts/perf/security reports, 7-min demo recording.
- Tracked under workstream `2026-07-19-pymentor-lab-v1.1`
  (FE-012..026, BE-017..030, INT-008..012).

## 🔒 Security notes

- The real `.env` is **gitignored** — never commit secrets or provider keys.
- Renderers (apps/web, apps/admin, Electron renderer) **must not** access
  Node.js, the filesystem, shell commands, or provider keys.
- Provider credentials are encrypted at rest (`PYMENTOR_PROVIDER_MASTER_KEY`).
- See [`AGENTS.md`](AGENTS.md) § "Agent Workflow & Security" for the full policy.

## 📄 License

**Proprietary — All Rights Reserved.** This software is **not open source** and
**not for commercial use**. It is published privately for competition review,
authorized collaborators, and non-commercial academic use within the 2026
competition cycle. See [`LICENSE`](LICENSE) for the full terms. Third-party
dependency notices belong in `NOTICE`.

---

<sub>Built for the higher-education Python classroom. Deterministic mastery,
LLM-assisted learning.</sub>
