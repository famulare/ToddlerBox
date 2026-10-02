#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

source "${ROOT_DIR}/scripts/lib/uv-env.sh"

if [ -d ".venv" ]; then
  if [ "${UV_VENV_CLEAR:-0}" = "1" ]; then
    uv venv --clear .venv
  else
    echo "Using existing virtual environment at .venv"
  fi
else
  uv venv .venv
fi
uv pip install -e ".[dev]"

APP="${1:-launcher}"
case "$APP" in
  launcher|paint|photos|typing|music)
    uv run python -m "toddlerbox.${APP}"
    ;;
  tests|test)
    uv run pytest
    ;;
  *)
    echo "Usage: $0 [launcher|paint|photos|typing|music|tests]" >&2
    exit 2
    ;;
esac
