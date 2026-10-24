from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import uuid

from .safeio import SafeTree, atomic_json


@dataclass(frozen=True)
class Paths:
    config: Path = Path('/etc/toddlerbox-sync')
    state: Path = Path('/var/lib/toddlerbox-sync')
    data: Path = Path('/var/lib/toddlerbox')

    @property
    def library(self):
        return self.data / 'photos/library'


def now():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def private_directory(path):
    path = Path(path)
    with SafeTree(path.parent) as tree:
        try:
            os.mkdir(path.name, 0o700, dir_fd=tree.fd)
            os.fsync(tree.fd)
        except FileExistsError:
            pass
        fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=tree.fd)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError('Sync directory must be owned by its administrator, mode 0700')
        finally:
            os.close(fd)


def initialize(paths):
    private_directory(paths.config)
    private_directory(paths.state)
    private_directory(paths.state/'staging')
    device = paths.state/'device.json'
    if not device.exists():
        atomic_json(device, {'version':1, 'uuid':str(uuid.uuid4())})
    value = load(device)
    if value.get('version') != 1 or str(uuid.UUID(value['uuid'])) != value['uuid']:
        raise ValueError('Invalid persistent device identity')
    return value['uuid']


def load(path, default=None):
    path = Path(path)
    with SafeTree(path.parent) as tree:
        try:
            return json.loads(tree.read(path.name, limit=4*1024**2))
        except FileNotFoundError:
            return {} if default is None else default


def clock_plausible(versions=Path('/opt/toddlerbox/versions.env'), *, current=None):
    """False when the clock predates this system's build (a flat CMOS battery)."""
    try:
        text = Path(versions).read_text()
    except OSError:
        return True
    for line in text.splitlines():
        if line.startswith('UBUNTU_SNAPSHOT='):
            try:
                built = dt.datetime.strptime(line.split('=', 1)[1].strip(), '%Y%m%dT%H%M%SZ')
            except ValueError:
                return True
            current = current or dt.datetime.now(dt.timezone.utc)
            return current >= built.replace(tzinfo=dt.timezone.utc)
    return True


def sweep_staging(paths):
    """Remove staging a killed job or import left behind. Call only while holding the lock."""
    with SafeTree(paths.state/'staging') as tree:
        for name in os.listdir(tree.fd):
            info = os.stat(name, dir_fd=tree.fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                shutil.rmtree(name, dir_fd=tree.fd)
            else:
                os.unlink(name, dir_fd=tree.fd)
        os.fsync(tree.fd)


@contextmanager
def lock(paths):
    with SafeTree(paths.state) as tree:
        fd = os.open('job.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=tree.fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise ValueError('Invalid sync lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def finalize(paths, result):
    value = load(paths.state/'status.json')
    if value.get('state') == 'running':
        value['state'] = 'timed_out' if result == 'timeout' else 'interrupted'
        value['completed_at'] = now()
        value.setdefault('issues', []).append('job-'+value['state'])
        value['issue_count'] = value.get('issue_count',0) + 1
        atomic_json(paths.state/'status.json', value)
