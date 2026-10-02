#!/usr/bin/env bash
set -euo pipefail
cat >&2 <<'HELP'
Global keyd mappings are retired. The bootable system uses a standalone Cage
session and session-scoped logind inhibitors. Parent GNOME retains normal input.
See system/README.md. This script does not modify the host.
HELP
exit 2
