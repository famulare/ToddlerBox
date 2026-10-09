#!/bin/sh
# Explicit source-checkout patch for an existing Ubuntu appliance; no apt/network.
set -eu
cd "$(dirname "$0")/.."
exec /usr/bin/python3 - "$PWD" <<'PY'
import datetime
import os
from pathlib import Path
import sys
sys.path.insert(0, '/usr/local/lib/toddlerbox-system')
from appliance import guard, maintenance_lock
from boot_recovery import STATE, atomic, safe

source = Path(sys.argv[1])
if os.geteuid() != 0:
    raise SystemExit('Run with sudo from authenticated parent mode.')
guard()
os_release = Path('/etc/os-release').read_text()
if 'ID=ubuntu\n' not in os_release or 'VERSION_ID="24.04"' not in os_release:
    raise SystemExit('This patch supports the existing Ubuntu 24.04 appliance only.')
files = {
    'system/tbx_sync/usb_setup.py': ('usr/local/lib/toddlerbox-system/tbx_sync/usb_setup.py', 0o644),
    'system/tbx_sync/cli.py': ('usr/local/lib/toddlerbox-system/tbx_sync/cli.py', 0o644),
    'system/bin/toddlerbox-maintenance': ('usr/local/sbin/toddlerbox-maintenance', 0o755),
}
# Read all selected public source bytes before touching installed software.
payload = {name: (source / name).read_bytes() for name in files}
for name in payload:
    compile(payload[name], name, 'exec')
with maintenance_lock():
    guard()
    backup = safe(Path('/'), STATE / ('drive-setup-patch-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')))
    backup.mkdir(mode=0o700)
    for name, (relative, mode) in files.items():
        target = safe(Path('/'), Path(relative))
        if target.exists():
            atomic(backup / target.name, target.read_bytes())
    # Dependency before caller: interruption leaves a valid old/new setup path.
    for name, (relative, mode) in files.items():
        atomic(safe(Path('/'), Path(relative)), payload[name], mode)
print('USB setup patch installed; original controls backed up privately.')
print('Open Set Up ToddlerBox Drive again, or run: sudo toddlerbox-sync setup')
print('Child work, Drive credentials, device identity and setup progress were not reset.')
print('This patch does not install the separate audio application changes.')
PY
