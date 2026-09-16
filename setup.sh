#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source "${ROOT}/packages.env.sh"

ENV_FILE=".env"
ENV_EXAMPLE=".env.example"

info()  { printf "\033[1;34m==> %s\033[0m\n" "$1"; }
ok()    { printf "\033[1;32m==> %s\033[0m\n" "$1"; }
warn()  { printf "\033[1;33m==> %s\033[0m\n" "$1"; }
fail()  { printf "\033[1;31mERROR: %s\033[0m\n" "$1"; exit 1; }

mkdir -p "${PACKAGES_DIR}"/{bin,uv-cache,uv-python,uv-tools,hf-cache,xdg-cache,npm-cache,pnpm,pnpm-store}

command -v uv >/dev/null 2>&1 || fail "uv not found on PATH (expected ${PACKAGES_DIR}/bin/uv)."

if [ -x "${SPICA_VENV}/bin/python" ]; then
  info "uv env at ${SPICA_VENV} already exists — reusing it"
else
  info "Creating uv env 'spica' at ${SPICA_VENV} (Python 3.12)..."
  uv venv "${SPICA_VENV}" --python 3.12
  ok "uv env created"
fi

# shellcheck disable=SC1091
source "${SPICA_VENV}/bin/activate"

info "Installing CPU-only Python dependencies with uv pip into ${SPICA_VENV}..."
uv pip install --python "${SPICA_VENV}/bin/python" --index-strategy unsafe-best-match -r requirements.txt
ok "Dependencies installed"

if [ -f "$ENV_FILE" ]; then
  warn ".env already exists — skipping copy (review $ENV_EXAMPLE for new vars)"
else
  info "Copying $ENV_EXAMPLE → $ENV_FILE..."
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  ok ".env created — set OPENAI_API_KEY (or backend/.llm_enpoints/.openai_key)"
fi

mkdir -p backend/process_user_data/.files .logs data/.phrase_audio backend/.llm_enpoints

if command -v pnpm >/dev/null 2>&1; then
  info "Installing frontend dependencies (pnpm store: ${PACKAGES_DIR}/pnpm-store)..."
  pnpm --dir frontend install --store-dir "${PACKAGES_DIR}/pnpm-store" --silent
  ok "Frontend dependencies installed"
else
  warn "pnpm not found — install Node 22+ under ${PACKAGES_DIR}/node"
fi

echo ""
ok "Setup complete!"
echo ""
echo "  Activate the environment:"
echo "    source ${SPICA_VENV}/bin/activate"
echo ""
echo "  Start the full stack:"
echo "    ./run.sh"
echo "    # FastAPI on :5002 · React on :5001"
echo ""
