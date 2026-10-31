#!/usr/bin/env python3
"""Run bounded external sampling, then export only allowlisted app-stage metrics."""
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import tempfile

ROOT = Path('/home/parent/toddlerbox/build')
METRICS = {'event_batch', 'render_work', 'display_flip', 'clock_tick', 'frame_interval',
           'autosave_snapshot', 'event_pump', 'sdl_touch_queue_age'}
COUNTS = {'events_received', 'pointer_accepted', 'pointer_rejected',
          'queued_touch_samples', 'touch_queue_sample_capped'}


def number(value):
    return type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 1e12


def sanitize(value):
    result = {'metrics': {}, 'counts': {}, 'context': {}}
    for name, entry in value.get('metrics', {}).items():
        if name not in METRICS or not isinstance(entry, dict):
            continue
        buckets = entry.get('buckets', [])
        if len(buckets) != 15 or not all(number(v) for v in buckets):
            continue
        if not all(number(entry.get(k)) for k in ['count', 'sum_ms', 'max_ms']):
            continue
        result['metrics'][name] = {k: entry[k] for k in ['count', 'sum_ms', 'max_ms', 'buckets']}
    result['counts'] = {k: v for k, v in value.get('counts', {}).items() if k in COUNTS and number(v)}
    result['sdl_touch_queue_available'] = value.get('sdl_touch_queue_available') is True
    result['windows'] = []
    for window in value.get('windows', [])[-60:]:
        if not isinstance(window, dict) or not number(window.get('seconds')):
            continue
        metrics = {}
        for name, entry in window.get('metrics', {}).items():
            if name in METRICS and isinstance(entry, dict) and all(
                    number(entry.get(k)) for k in ['count', 'sum_ms', 'max_ms']):
                metrics[name] = {k: entry[k] for k in ['count', 'sum_ms', 'max_ms']}
        result['windows'].append({'seconds': window['seconds'], 'metrics': metrics,
                                  'counts': {k: v for k, v in window.get('counts', {}).items()
                                             if k in COUNTS and number(v)}})
    result['tool_changes'] = [
        {'seconds': entry['seconds'], 'tool': entry['tool']}
        for entry in value.get('tool_changes', [])[-64:]
        if isinstance(entry, dict) and number(entry.get('seconds'))
        and entry.get('tool') in {'round', 'fountain', 'eraser', 'bucket'}]
    context = value.get('context', {})
    for name in ['screen_size', 'canvas_size', 'sdl_version']:
        values = context.get(name)
        if isinstance(values, list) and len(values) in {2, 3} and all(number(v) for v in values):
            result['context'][name] = values
    for name in ['canvas_bytes_per_pixel', 'canvas_flags']:
        if number(context.get(name)):
            result['context'][name] = context[name]
    for name in ['video_driver', 'compositor_hint', 'sdl_renderer_hint']:
        if context.get(name) in {'wayland', 'x11', 'dummy', 'pixman', 'gles2', 'software', 'opengl', 'opengles2', None}:
            result['context'][name] = context.get(name)
    return result


def read_reports(directory):
    reports = []
    for path in sorted(directory.glob('paint-timing-*.json'))[-32:]:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                    continue
                value = json.loads(stream.read(65537))
            reports.append(sanitize(value))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return reports


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run through the parent-authorized bounded diagnostic service.')
    spec = importlib.util.spec_from_file_location('session_collector', Path(__file__).with_name('collect-paint-session.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUTPUT = ROOT / 'paint-timing-cpu-baseline.json'
    module.main()
    report = {'scope': 'software stage timings; not physical finger-to-photon',
              'desktop': read_reports(ROOT / 'paint-desktop-test/data/logs'),
              'child': read_reports(Path('/var/lib/toddlerbox/logs')),
              'bucket_upper_bounds_ms': [.1, .25, .5, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1000, 'overflow']}
    fd, name = tempfile.mkstemp(prefix='.paint-timing-export-', dir=ROOT)
    with os.fdopen(fd, 'w') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    os.replace(name, ROOT / 'paint-timing-session-results.json')
    os.chmod(ROOT / 'paint-timing-session-results.json', 0o644)


if __name__ == '__main__':
    main()
