#!/usr/bin/env bash
# PyMentor Lab v1.1 — healthcheck (Linux / macOS).
#
# Polls the API /health endpoint and prints `docker compose ps` for the
# pymentor-prod project. Exits 0 when healthy, non-zero after the timeout.
#
#   ./healthcheck.sh [timeout_seconds]   (default 120)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PROJECT_NAME="pymentor-prod"
HEALTH_URL="http://localhost:8000/health"
TIMEOUT="${1:-120}"

log() { printf '[health] %s\n' "$*"; }
err() { printf '[health][ERROR] %s\n' "$*" >&2; }

if ! command -v curl >/dev/null 2>&1; then
    err "curl is required (used to probe $HEALTH_URL)."
    exit 1
fi

elapsed=0
while [ "$elapsed" -lt "$TIMEOUT" ]; do
    if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
        log "API healthy ($HEALTH_URL, waited ${elapsed}s)."
        if docker compose version >/dev/null 2>&1 && [ -d "code" ]; then
            ( cd code && docker compose -p "$PROJECT_NAME" ps ) || true
        fi
        exit 0
    fi
    sleep 3
    elapsed=$((elapsed + 3))
    printf '.'
done
echo

err "API not healthy after ${TIMEOUT}s."
if [ -d "code" ] && docker compose version >/dev/null 2>&1; then
    ( cd code && docker compose -p "$PROJECT_NAME" ps ) || true
    err "Recent API logs:"
    ( cd code && docker compose -p "$PROJECT_NAME" logs --tail=40 api ) || true
fi
exit 1
