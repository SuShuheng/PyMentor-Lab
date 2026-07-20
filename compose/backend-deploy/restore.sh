#!/usr/bin/env bash
# Restores a gzipped PostgreSQL dump produced by backup.sh.
#   ./restore.sh backups/pymentor-20260719-120000.sql.gz
set -euo pipefail
cd "$(dirname "$0")"

file="${1:-}"
[ -n "$file" ] || { echo "Usage: $0 <backup-file>" >&2; exit 1; }
[ -f "$file" ] || { echo "Backup file not found: $file" >&2; exit 1; }

echo "==> Restoring PostgreSQL from $file..."
gunzip -c "$file" | docker compose exec -T postgres psql -U pymentor pymentor
echo "    OK  Restore complete."
