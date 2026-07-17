# syntax=docker/dockerfile:1
# Sandbox runtime image (Python 3.13).
#
# This is the untrusted-student execution boundary. The pinned image contains
# only the trusted harness and Python standard library — no Docker client and
# no service secret. The Supervisor (separate image) orchestrates this image
# via the executor in sandbox/executor.py, which builds the hardened
# `docker run` argument list: network=none, read-only root, tmpfs work dir,
# non-root numeric UID/GID, all capabilities dropped, no-new-privileges,
# bounded memory/cpu/pids/fsize/nofile, no restart, --rm cleanup.
#
# Network and host mounts are denied at run time by the executor, not by this
# image; the contract is enforced in sandbox/executor.build_container_args.
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.7

COPY pyproject.toml ./
COPY backend ./backend
COPY sandbox ./sandbox

RUN uv pip install --system -e ".[dev]"

# Create the fixed non-root student identity the executor pins via --user.
# UID/GID 10001 matches SANDBOX_CHILD_UID/SANDBOX_CHILD_GID in sandbox/executor.py.
RUN groupadd --gid 10001 student && \
    useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin student

# Entrypoint matches the fixed command the executor assembles:
# `python -S -m sandbox.harness`. The harness reads one authenticated,
# length-prefixed request frame from stdin and writes exactly one trusted
# protocol frame to stdout.
ENTRYPOINT ["python", "-S", "-m", "sandbox.harness"]
