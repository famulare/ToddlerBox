#!/usr/bin/env bash
set -euo pipefail
# Parent recovery keeps the installed child session available for repair.
exec sudo /usr/local/sbin/toddlerbox-mode parent
