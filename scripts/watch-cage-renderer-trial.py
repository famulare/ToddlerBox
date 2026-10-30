#!/usr/bin/env python3
"""Bound one standalone GPU-renderer trial; preserve ordinary startup/recovery."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

FLAG = Path('/run/toddlerbox-system/cage-renderer-trial')
OUTPUT = Path('/home/parent/toddlerbox/build/cage-renderer-trial-result.json')
STOP = False


def stop(_signum, _frame):
    global STOP
    STOP = True


def gles_cage_present():
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if (proc / 'comm').read_text().strip() not in {'cage', 'toddlerbox-cage'}:
                continue
            if b'WLR_RENDERER=gles2' in (proc / 'environ').read_bytes().split(b'\0'):
                return True
        except OSError:
            continue
    return False


def mode():
    try:
        return Path('/run/toddlerbox-system/mode').read_text().strip()
    except OSError:
        return 'unknown'


def parent():
    try:
        return subprocess.run(['/usr/local/sbin/toddlerbox-mode', 'parent'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=12).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def record(value):
    fd, name = tempfile.mkstemp(prefix='.cage-trial-', dir=OUTPUT.parent)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
    os.replace(name, OUTPUT)
    os.chmod(OUTPUT, 0o644)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run through the bounded parent-authorized trial service.')
    if mode() != 'parent' or FLAG.exists() or FLAG.is_symlink():
        raise SystemExit('Parent mode and no existing renderer trial are required.')
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    started = time.clock_gettime(time.CLOCK_BOOTTIME)
    deadline = started + 240
    fd = os.open(FLAG, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'w') as stream:
        stream.write(f'gles2 {int(deadline)}\n')
        os.fchmod(stream.fileno(), 0o644)
    result = {'status': 'armed', 'gles_cage_observed': False,
              'ordinary_default': 'pixman', 'deadline_seconds': 240}
    record(result)
    child_since = None
    try:
        while not STOP and time.clock_gettime(time.CLOCK_BOOTTIME) < deadline:
            now = time.clock_gettime(time.CLOCK_BOOTTIME)
            if gles_cage_present():
                result['gles_cage_observed'] = True
                # The running Cage has its environment. Remove the one-shot
                # request immediately so any subsequent restart uses pixman.
                FLAG.unlink(missing_ok=True)
            current = mode()
            if result['gles_cage_observed'] and current == 'parent':
                result['status'] = 'returned-to-parent'
                break
            if current == 'child' and child_since is None:
                child_since = now
            if child_since is not None and not result['gles_cage_observed'] and now - child_since > 20:
                result['status'] = 'gles-start-not-observed'
                result['parent_requested'] = parent()
                break
            time.sleep(.1)
        else:
            result['status'] = 'interrupted' if STOP else 'deadline'
            if mode() == 'child':
                result['parent_requested'] = parent()
    finally:
        FLAG.unlink(missing_ok=True)
        result['override_removed'] = not FLAG.exists()
        result['elapsed_boottime_seconds'] = round(time.clock_gettime(time.CLOCK_BOOTTIME) - started, 2)
        record(result)


if __name__ == '__main__':
    main()
