#!/usr/bin/env bash
set -euo pipefail
cat >&2 <<'HELP'
The in-place kiosk configurator has been retired. Build the Ubuntu system with:
  ./system/build.sh
Test it with:
  ./system/vm.sh start
See system/README.md. This script does not modify the host.
HELP
exit 2
