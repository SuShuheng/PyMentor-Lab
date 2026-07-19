#!/usr/bin/env bash
# PyMentor Lab v1.1 — upgrade / rebuild (Linux / macOS).
#
# Pulls latest base images, rebuilds every service image from the code/ tree,
# and restarts the stack with the existing volumes intact (so Postgres, Redis,
# and MinIO data survive).
#
# IMPORTANT: take a backup BEFORE upgrading:
#   ./backup.sh
# If anything goes wrong, see rollback.sh (local-build rollback = DB restore).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE=".env"
PROJECT_NAME="pymentor-prod"

log() { printf '[upgrade] %s\n' "$*"; }
err() { printf '[upgrade][ERROR] %s\n' "$*" >&2; }
die() { err "$*"; exit 1; }

if [ ! -f "$ENV_FILE" ]; then
    die ".env not found. Run ./deploy.sh first to create it from .env.example."
fi
if [ ! -d "code" ]; then
    die "Missing 'code/' directory. Re-extract the new backend-deploy archive over this folder."
fi

log "Pulling base images and rebuilding services from code/ ..."
(
    cd code
    docker compose -p "$PROJECT_NAME" --env-file ../.env build --pull
    docker compose -p "$PROJECT_NAME" --env-file ../.env up -d
)

log "Upgrade complete."
cat <<EOF

==============================================================================
  Upgrade finished — next steps
==============================================================================
  Verify health:    ./healthcheck.sh
  Tail logs:        (cd code && docker compose -p $PROJECT_NAME logs -f)

  ROLLBACK: local builds have no image registry tags, so rollback is
  database restore, not image re-tag. If you need to undo this upgrade:
    1. ./rollback.sh            (runs docker compose down + restore latest backup)
    2. OR ./restore.sh backups/<latest>.sql.gz
  Always run ./backup.sh BEFORE upgrading.
==============================================================================
EOF
