"""Explicitly armed, bounded local timing diagnostics; never record child content."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time

FLAG = Path('/run/toddlerbox-system/paint-timing.json')
BOUNDS_MS = (.1, .25, .5, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1000)


class PaintTiming:
    def __init__(self, output: Path, expires: float, *, clock=time.monotonic):
        self.output, self.expires, self.clock = output, expires, clock
        self.metrics = {}
        self.counts = {}
        self.context = {}
        self.lock = threading.Lock()
        self.last_frame = None

    @classmethod
    def armed(cls, data_root: Path):
        try:
            info = FLAG.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 1024:
                return None
            config = json.loads(FLAG.read_text())
            expires = float(config['expires_monotonic'])
            remaining = expires - time.monotonic()
            if not 0 < remaining <= 600:
                return None
            probe = cls(data_root / f'logs/paint-timing-{os.getpid()}-{time.monotonic_ns()}.json', expires)
            threading.Thread(target=probe._writer, name='paint-timing', daemon=True).start()
            return probe
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def observe(self, name: str, seconds: float):
        if self.clock() >= self.expires:
            return
        value = max(0., seconds * 1000)
        bucket = next((i for i, bound in enumerate(BOUNDS_MS) if value <= bound), len(BOUNDS_MS))
        with self.lock:
            metric = self.metrics.setdefault(name, {'count': 0, 'sum_ms': 0., 'max_ms': 0.,
                                                     'buckets': [0] * (len(BOUNDS_MS) + 1)})
            metric['count'] += 1
            metric['sum_ms'] += value
            metric['max_ms'] = max(metric['max_ms'], value)
            metric['buckets'][bucket] += 1

    def count(self, name: str, amount: int = 1):
        if self.clock() < self.expires:
            with self.lock:
                self.counts[name] = self.counts.get(name, 0) + amount

    def frame(self):
        now = self.clock()
        if self.last_frame is not None:
            self.observe('frame_interval', now - self.last_frame)
        self.last_frame = now

    def snapshot(self):
        with self.lock:
            metrics = {name: {**m, 'buckets': list(m['buckets'])} for name, m in self.metrics.items()}
            counts = dict(self.counts)
        return {'status': 'completed' if self.clock() >= self.expires else 'collecting',
                'bucket_upper_bounds_ms': [*BOUNDS_MS, 'overflow'], 'metrics': metrics,
                'context': dict(self.context), 'counts': counts,
                'content_recorded': False, 'latency_scope': 'app stages; not physical finger-to-photon'}

    def _writer(self):
        # All diagnostic storage stays on this expendable daemon, never the UI thread.
        while True:
            report = self.snapshot()
            temporary = None
            try:
                fd, name = tempfile.mkstemp(prefix='.paint-timing-', dir=self.output.parent)
                temporary = Path(name)
                with os.fdopen(fd, 'w') as stream:
                    json.dump(report, stream)
                    stream.write('\n')
                os.replace(temporary, self.output)
            except OSError:
                pass  # Diagnostic failure cannot affect drawing or child work.
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            if report['status'] == 'completed':
                return
            time.sleep(min(2., max(.01, self.expires - self.clock())))
