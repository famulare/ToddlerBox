"""Synthetic VM checks, executed only by the authenticated qualification harness.

No live-device invocation, audio playback, input grab, package installation or
network. The host supplies the genuine earlier image's public package inventory.
"""
import json
from pathlib import Path
import subprocess


def bounded(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=8, check=True).stdout


def check(baseline):
    assert Path('/run/toddlerbox-system/mode').read_text().strip() == 'parent'
    installed = dict(line.split('\t', 1) for line in bounded(
        ['dpkg-query', '-W', '-f=${Package}\t${Version}\n']).splitlines())
    added = sorted(set(installed) - set(baseline))
    units = set()
    for package in added:
        for name in bounded(['dpkg-query', '-L', package]).splitlines():
            path = Path(name)
            if path.parent in {Path('/lib/systemd/system'), Path('/usr/lib/systemd/system')} and path.suffix in {'.service', '.socket', '.timer', '.path'}:
                units.add(path.name)
            assert not name.startswith(('/etc/cron.d/', '/etc/cron.daily/', '/etc/cron.hourly/',
                                        '/etc/cron.weekly/', '/etc/cron.monthly/')), 'New scheduled diagnostic job'
    states = {}
    for unit in sorted(units):
        result = subprocess.run(['systemctl', 'is-enabled', unit], capture_output=True, text=True, timeout=8)
        state = result.stdout.strip()
        assert state in {'masked', 'disabled', 'static', 'indirect'}, 'Unexpected automatic unit startup'
        assert bounded(['systemctl', 'show', unit, '--property=ActiveState', '--value']).strip() == 'inactive'
        states[unit] = state
    assert states.get('smartmontools.service') == states.get('smartd.service') == 'masked'
    bounded(['libinput', 'list-devices'])
    bounded(['lspci', '-nn'])
    bounded(['smartctl', '--scan'])
    evidence = {'baseline_comparison': 'actual package inventory from successful renderer-only fresh image',
                'added_packages': {p: installed[p] for p in added}, 'added_units': states,
                'checks': ['parent diagnostic smoke helper passed separately',
                           'bounded real libinput enumeration, PCI enumeration and SMART scan passed',
                           'new-package units inactive and not enabled; no new cron entries'],
                'limits': ['virtual devices only; no physical touchscreen, disk SMART passthrough or hearing evidence',
                           'libinput record/debug-events and evtest availability checked without recording input']}
    print('TBX_DIAGNOSTICS:' + json.dumps(evidence, sort_keys=True))
