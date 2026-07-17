# syntax=docker/dockerfile:1
# Sandbox runner image (Python 3.13).
# Isolation (no network, bounded resources) is enforced at runtime; the strict
# process/filesystem isolation lands in BE-005.
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.7

COPY pyproject.toml ./
COPY backend ./backend
COPY sandbox ./sandbox

RUN uv pip install --system -e ".[dev]"

# Placeholder entrypoint; BE-005 replaces this with the isolated runner server.
CMD ["python", "-c", "print('sandbox runner placeholder')"]
