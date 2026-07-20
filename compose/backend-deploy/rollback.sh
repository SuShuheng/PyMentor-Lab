#!/usr/bin/env bash
# Rollback: stops the stack; re-run deploy.sh from a previous code/ snapshot.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> PyMentor Lab rollback starting..."
echo "    Stopping current stack..."
docker compose down
echo "    OK  Stack stopped. Re-run deploy.sh from the previous code/ snapshot to finish rollback."
echo "    (No image cache lookup in v1.1 - keep a copy of each code/ snapshot you wish to roll back to.)"
