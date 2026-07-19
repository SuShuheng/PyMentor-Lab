#!/usr/bin/env bash
# PyMentor Lab v1.1 — rollback (Linux / macOS).
#
# HONEST ROLLBACK MODEL
# ---------------------
# This deployment package builds images locally (no registry). That means there
# are no per-version image tags to switch back to. A real image-tag rollback
# requires pushing images to a registry; we have not done that here.
#
# What this script actually does:
#   1. Stops the running stack (docker compose down) — volumes are preserved.
#   2. Restores Postgres from a backup file. By default the newest file under
#      ./backups/. Pass an explicit path to choose a different one:
#          ./rollback.sh backups/pymentor-20260719-103015.sql.gz
#
# To roll back the CODE (not just the data), drop the previous backend-deploy
# archive in place of code/, then run ./upgrade.sh. Always ./backup.sh first.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE=".env"
PROJECT_NAME="pymentor-prod"
BACKUPS_DIR="backups"

log() { printf '[rollback] %s\n' "$*"; }
err() { printf '[rollback][ERROR] %s\n' "$*" >&2; }
die() { err "$*"; exit 1; }

if [ ! -f "$ENV_FILE" ]; then
    die ".env not found. Run ./deploy.sh first."
fi
if [ ! -d "code" ]; then
    die "Missing 'code/' directory."
fi

# Resolve the backup file: either the explicit arg, or the newest in ./backups.
BACKUP_FILE="${1:-}"
if [ -z "$BACKUP_FILE" ]; then
    if [ ! -d "$BACKUPS_DIR" ]; then
        die "No backup specified and no $BACKUPS_DIR/ directory exists. Nothing to roll back to."
    fi
    BACKUP_FILE="$(ls -1t "$BACKUPS_DIR"/*.sql.gz 2>/dev/null | head -n 1 || true)"
    if [ -z "$BACKUP_FILE" ]; then
        die "No *.sql.gz files found in $BACKUPS_DIR/. Pass an explicit path: ./rollback.sh <file.sql.gz>"
    fi
fi
if [ ! -f "$BACKUP_FILE" ]; then
    die "Backup file not found: $BACKUP_FILE"
fi

log "This will:"
log "  1. Stop the running stack (volumes preserved)."
log "  2. Restore Postgres from: $BACKUP_FILE"
log "This is DESTRUCTIVE — current DB contents will be overwritten."
printf 'Proceed? [y/N] '
read -r answer
case "$answer" in
    y|Y|yes|YES) ;;
    *) log "Aborted."; exit 0 ;;
esac

# --- 1. stop stack ------------------------------------------------------------------
log "Stopping stack (project: $PROJECT_NAME)..."
(
    cd code
    docker compose -p "$PROJECT_NAME" down
)

# --- 2. bring up just postgres so we can pipe a restore in --------------------------
log "Starting postgres only..."
(
    cd code
    docker compose -p "$PROJECT_NAME" up -d postgres
)

# Wait for postgres to be ready.
log "Waiting for postgres to accept connections..."
for _ in $(seq 1 60); do
    if ( cd code && docker compose -p "$PROJECT_NAME" exec -T postgres pg_isready -U pymentor ) >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# --- 3. restore ---------------------------------------------------------------------
log "Restoring from $BACKUP_FILE ..."
(
    cd code
    gunzip -c "../$BACKUP_FILE" | docker compose -p "$PROJECT_NAME" exec -T postgres psql -U pymentor pymentor
)

log "Restore complete."
cat <<EOF

==============================================================================
  Rollback finished
==============================================================================
  Postgres has been restored to the snapshot in:
    $BACKUP_FILE

  The application services are still stopped. To bring the full stack back up
  with the restored data, run:
    ./deploy.sh

  If you also need to revert CODE to a previous version, replace code/ with the
  previous backend-deploy archive's source, then run ./upgrade.sh.
==============================================================================
EOF
