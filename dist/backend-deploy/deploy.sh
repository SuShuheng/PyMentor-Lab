#!/usr/bin/env bash
# PyMentor Lab v1.1 — backend deployment entrypoint (Linux / macOS).
#
# Behaviour:
#   1. Verifies `docker compose` is available (errors with an install hint otherwise).
#   2. If `.env` is missing, copies `.env.example` to `.env`, prints clear
#      instructions to fill in the three [REQUIRED] secrets, and EXITS 0.
#      It will never auto-start with default secrets.
#   3. If `.env` exists, runs `docker compose -p pymentor-prod --env-file .env
#      up --build -d` from the `code/` directory, then waits for the API
#      healthcheck (loop curl on /health up to 180s) and prints the admin URL.
set -euo pipefail

# Resolve the directory this script lives in so it works from any cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE=".env"
ENV_EXAMPLE=".env.example"
PROJECT_NAME="pymentor-prod"
HEALTH_URL="http://localhost:8000/health"
HEALTH_TIMEOUT=180

log()  { printf '[deploy] %s\n' "$*"; }
err()  { printf '[deploy][ERROR] %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

# --- 1. docker compose availability ------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
    err "Docker engine is not installed or not on PATH."
    err "Install Docker Engine:  https://docs.docker.com/engine/install/"
    err "Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    err "'docker compose' (Compose V2 plugin) is not available."
    err "Install the compose plugin: https://docs.docker.com/compose/install/"
    err "On older Docker Desktop, enable 'Use Docker Compose V2' in Settings."
    exit 1
fi

# --- 2. .env handling ---------------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
    if [ ! -f "$ENV_EXAMPLE" ]; then
        die "Neither $ENV_FILE nor $ENV_EXAMPLE exists in $SCRIPT_DIR."
    fi
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    log "Created $ENV_FILE from $ENV_EXAMPLE."
    cat <<EOF

==============================================================================
  ACTION REQUIRED — edit .env before deploying
==============================================================================
  Open  $SCRIPT_DIR/.env  and set the three [REQUIRED] secrets:

    PYMENTOR_PROVIDER_MASTER_KEY      encryption key for provider credentials
    PYMENTOR_INITIAL_ADMIN_EMAIL      first admin login email (deliverable)
    PYMENTOR_INITIAL_ADMIN_PASSWORD   first admin login password

  Generation commands are documented inline in .env. Recommended:

    python -c "import base64,secrets; \\
      print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

  Also rotate the default dev values for:
    POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD,
    PYMENTOR_JWT_SECRET, PYMENTOR_WORKER_INTERNAL_SECRET, PYMENTOR_SANDBOX_SECRET

  Then re-run this script:
    ./deploy.sh
==============================================================================
EOF
    exit 0
fi

# --- 3. build + start ---------------------------------------------------------------
if [ ! -d "code" ]; then
    die "Missing 'code/' directory. This zip should have shipped with full source under code/. Re-extract the archive."
fi

log "Building and starting the stack (project: $PROJECT_NAME). First build may take several minutes..."
(
    cd code
    docker compose -p "$PROJECT_NAME" --env-file ../.env up --build -d
)

# --- 4. wait for API health ---------------------------------------------------------
log "Waiting for API health at $HEALTH_URL (up to ${HEALTH_TIMEOUT}s)..."
elapsed=0
healthy=0
while [ "$elapsed" -lt "$HEALTH_TIMEOUT" ]; do
    if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
        healthy=1
        break
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    printf '.'
done
echo

if [ "$healthy" -ne 1 ]; then
    err "API did not become healthy within ${HEALTH_TIMEOUT}s."
    err "Inspect logs with:  (cd code && docker compose -p $PROJECT_NAME logs --tail=200 api)"
    err "Check container status:  (cd code && docker compose -p $PROJECT_NAME ps)"
    exit 1
fi

log "Stack is healthy."
cat <<EOF

==============================================================================
  PyMentor Lab v1.1 is up
==============================================================================
  API docs (Swagger):   http://localhost:8000/docs
  Admin login:          http://localhost:8000/docs#/Auth/login_api_v1_auth_login_post
  Web app:              http://localhost:4173
  Admin app:            http://localhost:4174
  MinIO console:        http://localhost:9001
  Postgres (psql):      localhost:5432  (user/db: pymentor)

  Admin credentials are the ones you set in .env:
    PYMENTOR_INITIAL_ADMIN_EMAIL
    PYMENTOR_INITIAL_ADMIN_PASSWORD

  Useful commands:
    ./healthcheck.sh                 verify the stack is still healthy
    ./backup.sh                      take a gzipped SQL backup into ./backups/
    ./upgrade.sh                     rebuild + restart on a new source drop
    docker compose -p $PROJECT_NAME logs -f      tail service logs
==============================================================================
EOF
