#!/usr/bin/env python3
"""Six-minute passive local baseline. No grab, coordinates, keys or network.

Run as root in a transient system service with RuntimeMaxSec=420. Reports are
local diagnostics, not physical latency measurements or candidate acceptance.
"""
import collections
import json
import os
from pathlib import Path
import select
import signal
import struct
import tempfile
import time

OUTPUT = Path('/home/parent/toddlerbox/build/paint-latency-baseline.json')
EVENT = struct.Struct('@llHHi')
STOP = False


def process_label(comm, args=()):
    if comm == 'gnome-shell':
        return 'gnome'
    if comm in {'toddlerbox-cage', 'cage'}:
        return 'cage'
    if comm.startswith('python'):
        for module, label in [(b'toddlerbox.launcher', 'launcher'), (b'toddlerbox.paint', 'paint-direct')]:
            if list(args[1:3]) == [b'-m', module]:
                return label
    return None


def process_ticks(stat):
    fields = stat[stat.rindex(')') + 2:].split()
    return int(fields[11]) + int(fields[12]), int(fields[19])


def processes():
    values = {}
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            comm = (proc / 'comm').read_text().strip()
            args = (proc / 'cmdline').read_bytes().split(b'\0') if comm.startswith('python') else []
            label = process_label(comm, args)
            if label:
                ticks, start = process_ticks((proc / 'stat').read_text())
                values[(int(proc.name), start)] = (label, ticks)
        except (OSError, ValueError, IndexError):
            continue
    return values


def cpu_ticks():
    fields = [int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    return sum(fields), fields[3] + fields[4]


def stop(_signum, _frame):
    global STOP
    STOP = True


def publish(report):
    # Fixed local path, atomic checkpoint; never follow a substituted report link.
    if OUTPUT.is_symlink():
        raise ValueError('Refusing symlink output')
    fd, name = tempfile.mkstemp(prefix='.paint-baseline-', dir=OUTPUT.parent)
    temporary = Path(name)
    with os.fdopen(fd, 'w') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
        stream.flush()
    os.replace(temporary, OUTPUT)
    os.chmod(OUTPUT, 0o644)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo through systemd-run, bounded by RuntimeMaxSec=420.')
    if not OUTPUT.parent.is_dir():
        raise SystemExit('Expected local build directory.')
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    devices = [p for p in Path('/sys/class/input').glob('event*')
               if (p / 'device/name').read_text().strip() == 'ELAN0732:00 04F3:2B2A']
    if len(devices) != 1:
        raise SystemExit('Expected one known direct touchscreen; refusing other input devices.')
    fd = os.open(Path('/dev/input') / devices[0].name, os.O_RDONLY | os.O_NONBLOCK)
    counts = collections.Counter()
    report = {'status': 'collecting', 'limit_seconds': 360, 'exclusive_grab': False,
              'coordinates_or_keyboard_recorded': False, 'samples': [], 'touch_totals': {}}
    started = last = time.monotonic()
    deadline = started + 360
    previous = processes()
    previous_cpu = cpu_ticks()
    hz = os.sysconf('SC_CLK_TCK')
    publish(report)
    try:
        while not STOP and time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], .1)
            if ready:
                try:
                    data = os.read(fd, EVENT.size * 256)
                except BlockingIOError:
                    data = b''
                for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _, _, kind, code, value = EVENT.unpack_from(data, offset)
                    if kind == 3 and code == 57:
                        counts['down' if value >= 0 else 'up'] += 1
                    elif kind == 3 and code in {53, 54}:
                        counts['position_updates'] += 1
                    elif kind == 0 and code == 3:
                        counts['syn_dropped'] += 1
            now = time.monotonic()
            if now - last < 1:
                continue
            current = processes()
            usage = collections.defaultdict(float)
            for identity, (label, ticks) in current.items():
                if identity in previous:
                    usage[label] += 100 * max(0, ticks - previous[identity][1]) / hz / (now - last)
            total, idle = cpu_ticks()
            delta = total - previous_cpu[0]
            sample = {'elapsed_seconds': round(now - started, 2),
                      'process_cpu_percent_one_core': {k: round(v, 1) for k, v in usage.items()},
                      'total_cpu_percent': round(100 * (1 - (idle - previous_cpu[1]) / delta), 1) if delta else None,
                      'touch_cumulative': dict(counts)}
            try:
                mode = Path('/run/toddlerbox-system/mode').read_text().strip()
                sample['mode'] = mode if mode in {'parent', 'child'} else 'unknown'
            except OSError:
                sample['mode'] = 'unknown'
            try:
                sample['cpu0_khz'] = int(Path('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq').read_text())
            except (OSError, ValueError):
                pass
            report['samples'].append(sample)
            report['touch_totals'] = dict(counts)
            publish(report)
            previous, previous_cpu, last = current, (total, idle), now
        report['status'] = 'interrupted' if STOP else 'completed'
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        report['touch_totals'] = dict(counts)
        publish(report)
    finally:
        os.close(fd)


if __name__ == '__main__':
    main()
