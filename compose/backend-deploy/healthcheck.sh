#!/usr/bin/env bash
# Probe all compose services and report their status.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo ".env missing. Run deploy.sh first." >&2; exit 1; }

status="$(docker compose ps --format '{{.Name}} {{.Status}}' 2>/dev/null || true)"
echo "Service status:"
echo "$status" | sed 's/^/  /'

if echo "$status" | grep -viE '(healthy|running)' | grep -v '^$' >/dev/null 2>&1; then
  echo ""
  echo "Unhealthy services:" >&2
  echo "$status" | grep -viE '(healthy|running)' | grep -v '^$' | sed 's/^/  /' >&2
  exit 1
fi
echo ""
echo "All services healthy."
