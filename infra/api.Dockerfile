# syntax=docker/dockerfile:1
# FastAPI service image (Python 3.13).
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend:/app

WORKDIR /build

# Install uv for reproducible dependency resolution.
RUN pip install --no-cache-dir uv==0.11.7

COPY pyproject.toml README.md ./
COPY backend ./backend
COPY sandbox ./sandbox

RUN uv venv /opt/pymentor-venv && \
    uv pip install --python /opt/pymentor-venv/bin/python .

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/pymentor-venv/bin:$PATH \
    PYTHONPATH=/app/backend:/app

# pg_dump/pg_restore must match the Compose PostgreSQL 16 archive format.
RUN apt-get update && \
    apt-get install --no-install-recommends --yes ca-certificates curl && \
    install -d /usr/share/postgresql-common/pgdg && \
    curl --fail --silent --show-error --location \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        --output /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc && \
    . /etc/os-release && \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && \
    apt-get install --no-install-recommends --yes postgresql-client-16 && \
    apt-get purge --auto-remove --yes curl && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd --system pymentor && \
    useradd --system --gid pymentor --home-dir /nonexistent --shell /usr/sbin/nologin pymentor

COPY --from=builder /opt/pymentor-venv /opt/pymentor-venv
WORKDIR /app
COPY --chown=pymentor:pymentor backend ./backend
COPY --chown=pymentor:pymentor sandbox ./sandbox
COPY --chown=pymentor:pymentor knowledge ./knowledge

WORKDIR /app/backend
USER pymentor
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
