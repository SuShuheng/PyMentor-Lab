# syntax=docker/dockerfile:1
# Sandbox RUNTIME image (Python 3.13) — the untrusted-student execution boundary.
#
# This image contains ONLY the trusted harness and the Python standard library.
# It has no Docker client, no service secret, no application code, and no
# network egress. The Sandbox Supervisor (built from infra/sandbox.Dockerfile)
# orchestrates this image via sandbox/executor.py, which builds the hardened
# `docker run` argument list: network=none, read-only root, tmpfs work dir,
# non-root numeric UID/GID 10001, all capabilities dropped, no-new-privileges,
# bounded memory/cpu/pids/fsize/nofile, no restart, --rm cleanup.
#
# The pinned tag (1.0) must never be :latest; the executor passes --pull never
# so a missing image is a deterministic platform error, not a silent fetch.
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# The harness depends only on the Python standard library (ast, json, math, re,
# subprocess, etc.). No third-party packages and no pip/uv install step: the
# runtime image must stay minimal so the attack surface is the standard library
# alone.
COPY sandbox ./sandbox

# Create the fixed non-root student identity the executor pins via --user.
# UID/GID 10001 matches SANDBOX_CHILD_UID/SANDBOX_CHILD_GID in sandbox/executor.py.
# The account has no home directory and no login shell.
RUN groupadd --gid 10001 student && \
    useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin student && \
    # Remove package managers and networking tooling to shrink the image and
    # eliminate escape hatches a compromised child might reach for.
    apt-get purge -y --auto-remove \
        curl wget gnupg dirmngr ca-certificates apt apt-utils 2>/dev/null || true && \
    rm -rf /var/lib/apt/lists/*

# Entrypoint matches the fixed command the executor assembles:
# `python -S -m sandbox.harness`. -S skips site initialization so only the
# standard library is importable. The harness reads one authenticated,
# length-prefixed request frame from stdin and writes exactly one trusted
# protocol frame to stdout.
ENTRYPOINT ["python", "-S", "-m", "sandbox.harness"]
