#!/usr/bin/env bash
# Dumps PostgreSQL to backups/pymentor-YYYYMMDD-HHMMSS.sql.gz.
set -euo pipefail
cd "$(dirname "$0")"

stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p backups
out="backups/pymentor-$stamp.sql.gz"

echo "==> Dumping PostgreSQL -> $out"
docker compose exec -T postgres pg_dump -U pymentor pymentor 2>/dev/null | gzip > "$out"
[ -s "$out" ] || { echo "    ERR backup file empty" >&2; exit 1; }
size_kb="$(du -k "$out" | cut -f1)"
echo "    OK  Backup written (${size_kb} KB)."
