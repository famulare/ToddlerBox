from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
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
