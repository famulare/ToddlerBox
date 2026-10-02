#!/usr/bin/env bash
set -euo pipefail
# Compatibility entry point; GDM invokes the installed, versioned system recipe.
exec /usr/local/libexec/toddlerbox-session
