# syntax=docker/dockerfile:1
# FastAPI service image (Python 3.13).
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install uv for reproducible dependency resolution.
RUN pip install --no-cache-dir uv==0.11.7

COPY pyproject.toml ./
COPY backend ./backend

RUN uv pip install --system -e ".[dev]"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
