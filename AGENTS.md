# Repository Guidelines

## Project Structure & Module Organization

This repository hosts the PyMentor Lab V1.0 codebase. The V1.0 skeleton (M0-M2 integration + P0 backend deterministic engines + six-node LangGraph agent + five-resource pipeline + 14-chapter/93-node knowledge seed + Electron Windows unsigned package) has been merged to `main` via INT-007 (commit `557f0b3`, closed NOT-READY). The approved monorepo layout is `apps/web` (student UI), `apps/admin` (admin UI), `apps/desktop` (Electron main/preload), `backend/` (FastAPI), `workers/agent-worker/` (LangGraph.js), `sandbox/`, `packages/`, `knowledge/`, `infra/`, and `tests/`. `raw/` contains ignored competition and design inputs, not runtime code. Durable workflow records live in the sibling `../.making/pymentor-lab/` repository. Do not copy them into this repository. The V1.0 release is BLOCKED / NOT READY — see `docs/verification/release/v1.0-gap-report.md`; follow-on work is tracked under the `2026-07-19-pymentor-lab-v1.1` workstream.

## Build, Test, and Development Commands

Build scripts are committed. Canonical entry points (confirm each exists before use):

- `pnpm install` — install JavaScript workspace dependencies.
- `pnpm lint && pnpm test` — run TypeScript linting and Vitest suites.
- `python -m pytest backend/tests` — run FastAPI/domain tests.
- `docker compose up --build` — start PostgreSQL, Redis, object storage, API, Worker, and sandbox locally.

Confirm each script exists before use, and update this guide when canonical commands change.

## Coding Style & Naming Conventions

Use two spaces for TypeScript, TSX, JSON, and YAML; use four spaces for Python. Format TypeScript with Prettier and lint with ESLint. Format/lint Python with Ruff and type-check with mypy or pyright. Name React components `PascalCase`, hooks `useCamelCase`, TypeScript variables `camelCase`, and Python modules/functions `snake_case`. Keep shared DTOs serializable and versioned under `packages/contracts`.

## Testing Guidelines

Follow Red-Green-Refactor for behavior changes. Use Vitest for frontend/Worker units, pytest for backend/sandbox tests, and Playwright for cross-application E2E. Name tests `*.test.ts(x)` or `test_*.py`. Every fix needs a focused regression test; contract changes require Pydantic-Zod conformance coverage. No fixed coverage percentage is approved yet.

## Commit & Pull Request Guidelines

History has progressed past `Initial commit` through the V1.0 workstream (`2026-07-17-pymentor-lab-v1`); follow the approved Conventional Commits plan: `feat:`, `fix:`, `test:`, `docs:`, or `chore:`. Keep commits scoped to one task. PRs must cite the FE/BE/INT task ID, summarize risk, list commands and results, link issues, and include UI screenshots when applicable. Call out migrations, IPC, permissions, or secret-handling changes explicitly.

## Agent Workflow & Security

Before editing, read `../.making/pymentor-lab/PROJECT.md`, `CONTRACT.md`, the lane `TRACK.md`, and current `TASK.md`. Frontend owns renderer/UI paths; backend owns services, contracts, sandbox, infrastructure, and Electron privileges; integration starts only after declared dependencies finish. Never commit credentials, raw prompts, absolute machine paths, or generated secrets. Renderer code must not access Node.js, the filesystem, shell commands, or provider keys.
