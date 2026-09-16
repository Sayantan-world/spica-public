#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

export PYTHONWARNINGS="ignore::UserWarning:multiprocessing.resource_tracker"

# shellcheck disable=SC1091
source "${ROOT}/packages.env.sh"

if [ ! -x "${SPICA_VENV}/bin/python" ]; then
  echo "ERROR: uv env not found at ${SPICA_VENV}. Run ./setup.sh first." >&2
  exit 1
fi
# shellcheck disable=SC1091
source "${SPICA_VENV}/bin/activate"

PIDS=()

cleanup() {
  echo ""
  echo "Shutting down..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
  exit 0
}

trap cleanup INT TERM

echo "Starting FastAPI backend on :5002..."
uvicorn backend.api.main:app --host 0.0.0.0 --reload --port 5002 2>&1 &
PIDS+=($!)

echo "Waiting for backend..."
until curl -s http://127.0.0.1:5002/health >/dev/null 2>&1; do
  sleep 1
done
echo "Backend ready."

echo "Starting React frontend on :5001..."
pnpm --dir frontend dev --host 0.0.0.0 --port 5001 2>&1 &
PIDS+=($!)

echo "All services running. Open http://0.0.0.0:5001 (or this host's public IP on port 5001)."
echo "Ctrl+C to stop."
wait
