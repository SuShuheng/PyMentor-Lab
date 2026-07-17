# syntax=docker/dockerfile:1
# Sandbox SUPERVISOR image (Python 3.13).
#
# This is the trusted orchestrator — the only component allowed to create job
# containers. It runs the signed FastAPI Supervisor in sandbox/service.py and
# shells out to the Docker CLI through sandbox/executor.py. It has no database,
# Redis, object-store, provider, or JWT credential; its only secret is the
# HMAC shared secret used to verify execution requests from the FastAPI API.
#
# The runtime image (the untrusted boundary) is built separately from
# infra/sandbox-runtime.Dockerfile and is what the Supervisor launches per run.
# Compose binds the Supervisor to an internal-only network with no host port.
FROM python:3.13-slim AS supervisor

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.7

COPY pyproject.toml ./
COPY backend ./backend
COPY sandbox ./sandbox

RUN uv pip install --system -e ".[dev]"

# Install the Docker CLI so the executor can create/remove job containers.
# The daemon socket is supplied at run time (mounted read-only from the host or
# a rootless engine); it is NOT baked into the image.
RUN apt-get update && apt-get install -y --no-install-recommends docker.io && \
    rm -rf /var/lib/apt/lists/*

# The Supervisor reads its shared secret, runtime image reference, and request
# limits from the environment at startup (see backend/app/config.py SandboxSettings).
# Production startup rejects an unpinned runtime image or a short secret.
EXPOSE 8090

CMD ["uvicorn", "sandbox.service:create_app_factory", "--factory", "--host", "0.0.0.0", "--port", "8090"]
