#!/usr/bin/env bash
# PyMentor Lab v1.1 — Postgres restore (Linux / macOS).
#
# Restores Postgres from a gzipped SQL dump produced by ./backup.sh.
#
#   ./restore.sh backups/pymentor-20260719-103015.sql.gz
#
# DESTRUCTIVE: overwrites current DB contents. The stack must be running
# (./deploy.sh) so the postgres container is up; non-API services do not need
# to be stopped, but for a clean restore you may want to stop the API first:
#   (cd code && docker compose -p pymentor-prod stop api worker)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PROJECT_NAME="pymentor-prod"
DB_USER="${POSTGRES_USER:-pymentor}"
DB_NAME="${POSTGRES_DB:-pymentor}"

log() { printf '[restore] %s\n' "$*"; }
err() { printf '[restore][ERROR] %s\n' "$*" >&2; }
die() { err "$*"; exit 1; }

if [ "$#" -lt 1 ]; then
    cat <<EOF
Usage: $0 <backup.sql.gz>

Examples:
  $0 backups/pymentor-20260719-103015.sql.gz
  $0 \$(ls -1t backups/*.sql.gz | head -n 1)
EOF
    exit 2
fi

BACKUP_FILE="$1"
if [ ! -f "$BACKUP_FILE" ]; then
    die "Backup file not found: $BACKUP_FILE"
fi

if ! docker compose version >/dev/null 2>&1; then
    die "'docker compose' is not available."
fi
if [ ! -d "code" ]; then
    die "Missing 'code/' directory."
fi

log "About to restore Postgres from: $BACKUP_FILE"
log "Target database: user=$DB_USER db=$DB_NAME"
log "DESTRUCTIVE: current data in '$DB_NAME' will be overwritten."
printf 'Proceed? [y/N] '
read -r answer
case "$answer" in
    y|Y|yes|YES) ;;
    *) log "Aborted."; exit 0 ;;
esac

log "Restoring..."
(
    cd code
    gunzip -c "../$BACKUP_FILE" | docker compose -p "$PROJECT_NAME" exec -T postgres psql -U "$DB_USER" "$DB_NAME"
)

log "Restore complete. Verify with:"
log "  curl -sf http://localhost:8000/health"
log "  (cd code && docker compose -p $PROJECT_NAME exec -T postgres psql -U $DB_USER $DB_NAME -c '\\dt')"
