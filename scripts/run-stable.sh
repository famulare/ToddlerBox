#!/usr/bin/env bash
# Development-only process-exit check. The bootable system has its own watchdog.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
[[ -x .venv/bin/python ]] || { echo 'Run uv sync --extra dev first.' >&2; exit 1; }
for attempt in 1 2 3 4; do
    if .venv/bin/python -m toddlerbox.launcher; then
        exit 0
    fi
    if [[ $attempt -lt 4 ]]; then
        echo "Launcher failed; development retry $attempt/3" >&2
        sleep "$attempt"
    fi
done
echo 'Restart budget exhausted. Inspect data/logs/toddlerbox.log.' >&2
exit 1
