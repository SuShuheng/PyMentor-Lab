#!/usr/bin/env bash
# Upgrade: rebuild images + rolling recreate + healthcheck. Volumes preserved.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo ".env missing." >&2; exit 1; }

echo "==> PyMentor Lab upgrade starting..."
if [ "${1:-}" != "--no-build" ]; then
  echo "    Building new images..."
  docker compose build
fi
echo "    Recreating services (no volume loss)..."
docker compose up -d
echo "    Running healthcheck..."
./healthcheck.sh
