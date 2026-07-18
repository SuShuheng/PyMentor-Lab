# PyMentor Lab

A higher-education **Python learning system** that turns student interaction into
durable learning evidence, an eight-dimensional profile, a validated personalized
path, executable tasks, five resource types, assessment, mastery decisions, and
delayed review — with real multi-agent collaboration where an LLM never directly
decides formal mastery.

> **Status:** V1.0 competition release — bootstrap stage (`BE-001`).

## Repository layout (backend-owned bootstrap scope)

```
backend/                     FastAPI: API, deterministic domain, auth, Outbox
workers/agent-worker/        LangGraph.js: six-agent orchestration, resources
sandbox/                     Isolated Python student-code runner
packages/contracts/          Shared schemas: Pydantic ↔ Zod (frozen boundary)
packages/api-client/         Generated OpenAPI TypeScript SDK
knowledge/                   Course knowledge assets (14 chapters / 80+ nodes)
infra/                       Infrastructure configuration
docs/                        Documentation
scripts/                     Operational scripts
docker-compose.yml           One-command local start
pyproject.toml               Python tooling (ruff, mypy, pytest)
```

## Quick start

> Requires Node 20 LTS, Python 3.13, pnpm, uv, Docker.

```bash
# JavaScript workspace
pnpm install

# Python (uv fetches the 3.13 interpreter)
uv venv -p 3.13
uv pip install -e ".[dev]"

# Local services
docker compose up --build
```

## Commands

| Command | Purpose |
|---|---|
| `pnpm lint && pnpm test` | TypeScript lint and Vitest suites |
| `uv run ruff check && uv run mypy backend sandbox` | Python lint and types |
| `uv run pytest backend/tests` | FastAPI / domain tests |
| `pnpm contracts:check` | Pydantic ↔ Zod conformance gate |
| `docker compose up --build` | Start PostgreSQL, Redis, MinIO, API, Worker, Sandbox |

## License

CC BY-NC 4.0 (non-commercial, learning use only). Dependency notices in `NOTICE`.
