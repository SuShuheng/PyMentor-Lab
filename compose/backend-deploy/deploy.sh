#!/usr/bin/env bash
# ===========================================================================
#  PyMentor Lab - Backend deploy (Linux / macOS / WSL)
#  --------------------------------------------------------------------------
#  Usage (from this folder, after editing .env):
#      ./deploy.sh                # build + port check + start + healthcheck
#      ./deploy.sh --no-build     # reuse existing images (faster)
#      ./deploy.sh --fresh-db     # WARNING: deletes volumes + reseeds
#      ./deploy.sh --force-port   # auto-kill any process on a required port
#
#  Prerequisites:
#      - Docker + docker compose plugin installed and daemon running.
#      - .env present and at least these keys set:
#          PYMENTOR_PROVIDER_MASTER_KEY
#          PYMENTOR_INITIAL_ADMIN_EMAIL
#          PYMENTOR_INITIAL_ADMIN_PASSWORD
# ===========================================================================
set -euo pipefail

cd "$(dirname "$0")"

NO_BUILD=0
FRESH_DB=0
FORCE_PORT=0
for arg in "$@"; do
  case "$arg" in
    --no-build)  NO_BUILD=1 ;;
    --fresh-db)  FRESH_DB=1 ;;
    --force-port) FORCE_PORT=1 ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

REQUIRED_PORTS=(5432 6379 9000 9001 8000 8081 4173 4174)

echo "==> Checking prerequisites..."
if ! command -v docker >/dev/null 2>&1; then
  echo "    ERR docker not found on PATH. Install Docker first." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "    ERR Docker daemon is not running." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "    ERR docker compose plugin missing." >&2
  exit 1
fi
echo "    OK  Docker + Compose available."

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    echo "    !!  .env not found. Copying .env.example -> .env for first-time setup."
    cp .env.example .env
    echo "    ERR .env created with defaults. Edit it (set the three REQUIRED keys), then re-run deploy.sh." >&2
    echo "    Required keys:" >&2
    echo "      PYMENTOR_PROVIDER_MASTER_KEY"    >&2
    echo "      PYMENTOR_INITIAL_ADMIN_EMAIL"    >&2
    echo "      PYMENTOR_INITIAL_ADMIN_PASSWORD" >&2
    exit 2
  else
    echo "    ERR .env and .env.example both missing." >&2
    exit 1
  fi
fi

missing=()
for key in PYMENTOR_PROVIDER_MASTER_KEY PYMENTOR_INITIAL_ADMIN_EMAIL PYMENTOR_INITIAL_ADMIN_PASSWORD; do
  if ! grep -qE "^${key}=." .env; then
    missing+=("$key")
  fi
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "    ERR .env missing or empty required keys:" >&2
  for k in "${missing[@]}"; do echo "      $k" >&2; done
  exit 2
fi
echo "    OK  .env present and required keys set."

# --- Port occupancy check --------------------------------------------------
echo "==> Checking required ports..."
busy=()
for port in "${REQUIRED_PORTS[@]}"; do
  pid=""
  if command -v ss >/dev/null 2>&1; then
    pid="$(ss -ltnpH "sport = :$port" 2>/dev/null | awk 'NR>1 { gsub(/.*pid=/,"",$0); gsub(/,.*/,"",$0); print $0; exit }')"
  elif command -v lsof >/dev/null 2>&1; then
    pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n1)"
  fi
  if [ -n "$pid" ]; then
    busy+=("$port:$pid")
  fi
done

if [ ${#busy[@]} -gt 0 ]; then
  echo "    !!  The following ports are in use:" >&2
  for entry in "${busy[@]}"; do echo "      port $entry" >&2; done

  if [ "$FORCE_PORT" -eq 1 ]; then
    echo "    --force-port: killing offenders without prompting..."
  else
    read -r -p "Stop the listed process(es) now so the stack can bind? (y/N) " choice
    if [[ ! "$choice" =~ ^[Yy]$ ]]; then
      echo "    ERR Deploy aborted. Free the ports above (or rerun with --force-port)." >&2
      exit 3
    fi
  fi

  for entry in "${busy[@]}"; do
    pid="${entry#*:}"
    port="${entry%%:*}"
    echo "    Killing PID $pid on port $port..."
    kill -TERM "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
      sleep 1
    fi
    # Final verify
    if command -v ss >/dev/null 2>&1; then
      if ss -ltnH "sport = :$port" 2>/dev/null | grep -q ":$port"; then
        echo "    ERR Could not free port $port." >&2
        exit 3
      fi
    fi
  done
  echo "    OK  Ports freed."
else
  echo "    OK  All required ports free."
fi

if [ "$FRESH_DB" -eq 1 ]; then
  echo "==> --fresh-db: removing containers + volumes..."
  docker compose down -v
  echo "    OK  Volumes removed."
fi

if [ "$NO_BUILD" -eq 0 ]; then
  echo "==> Building images (docker compose build)..."
  docker compose build
  echo "    OK  Images built."
fi

echo "==> Starting stack (docker compose up -d)..."
docker compose up -d
echo "    OK  Stack started."

echo "==> Waiting for services to become healthy (up to 120s)..."
deadline=$(( $(date +%s) + 120 ))
all_healthy=0
while [ "$(date +%s)" -lt "$deadline" ]; do
  status="$(docker compose ps --format '{{.Name}} {{.Status}}' 2>/dev/null || true)"
  if ! echo "$status" | grep -viE '(healthy|running|^$)' >/dev/null 2>&1 || [ -z "$status" ]; then
    if [ -n "$status" ]; then all_healthy=1; break; fi
  fi
  sleep 5
done
if [ "$all_healthy" -eq 0 ]; then
  echo "    !!  Not all services healthy within 120s. Inspect with: docker compose ps"
  docker compose ps
else
  echo "    OK  All services healthy."
fi

echo ""
echo "=============================================================="
echo "  PyMentor Lab backend deployed"
echo "=============================================================="
echo "  API:     http://127.0.0.1:8000  (docs: /docs)"
echo "  Student: http://127.0.0.1:4173"
echo "  Admin:   http://127.0.0.1:4174"
echo "  MinIO:   http://127.0.0.1:9001"
echo "=============================================================="
