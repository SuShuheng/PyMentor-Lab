#!/usr/bin/env bash
# PyMentor Lab v1.1 — Postgres backup (Linux / macOS).
#
# Runs pg_dump inside the postgres container and writes a gzipped SQL dump to
# ./backups/pymentor-YYYYMMDD-HHMMSS.sql.gz. Safe to run while the stack is up.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PROJECT_NAME="pymentor-prod"
BACKUPS_DIR="backups"
DB_USER="${POSTGRES_USER:-pymentor}"
DB_NAME="${POSTGRES_DB:-pymentor}"

log() { printf '[backup] %s\n' "$*"; }
err() { printf '[backup][ERROR] %s\n' "$*" >&2; }
die() { err "$*"; exit 1; }

if ! docker compose version >/dev/null 2>&1; then
    die "'docker compose' is not available. Install the Compose V2 plugin."
fi
if [ ! -d "code" ]; then
    die "Missing 'code/' directory. Run from the backend-deploy folder."
fi

mkdir -p "$BACKUPS_DIR"

timestamp="$(date +%Y%m%d-%H%M%S)"
outfile="$BACKUPS_DIR/pymentor-$timestamp.sql.gz"

log "Running pg_dump (user=$DB_USER db=$DB_NAME) inside the postgres container..."
(
    cd code
    docker compose -p "$PROJECT_NAME" exec -T postgres pg_dump -U "$DB_USER" "$DB_NAME"
) | gzip > "$outfile"

if [ ! -s "$outfile" ]; then
    die "Backup file is empty — did the postgres container come up? Check: (cd code && docker compose -p $PROJECT_NAME ps postgres)"
fi

size="$(du -h "$outfile" | cut -f1)"
log "Backup complete."
printf '\n  path:  %s/%s\n  size:  %s\n\n' "$SCRIPT_DIR" "$outfile" "$size"
