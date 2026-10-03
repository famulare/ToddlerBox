from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import unicodedata

MAX_FILE = 50 * 1024 * 1024
MAX_TOTAL = 2 * 1024**3
RESERVE = 512 * 1024**2


def parts(name):
    if (not isinstance(name, str) or not name or len(name) > 512 or '\\' in name or
            ':' in name or unicodedata.normalize('NFC', name) != name or
            any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise ValueError('Unsafe relative path')
    result = name.split('/')
    if any(p in {'', '.', '..'} or len(p.encode()) > 240 for p in result):
        raise ValueError('Unsafe relative path')
    return result


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def reserve(fd, additional=0, minimum=RESERVE):
    fs = os.fstatvfs(fd)
    if fs.f_bavail * fs.f_frsize < minimum + additional:
        raise OSError(28, 'Disk reserve would be exhausted')


class SafeTree:
    """Dirfd traversal refuses symlinks at every component, including ancestors."""
    def __init__(self, root):
        root = Path(root).absolute()
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in root.parts[1:]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd

    def __enter__(self):
        return self

    def __exit__(self, *_):
        os.close(self.fd)

    @contextmanager
    def parent(self, name, *, create=False):
        components = parts(name)
        fd = os.dup(self.fd)
        try:
            for part in components[:-1]:
                if create:
                    try:
                        os.mkdir(part, 0o755, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd, components[-1]
        finally:
            os.close(fd)

    def read(self, name, *, limit=MAX_FILE):
        with self.parent(name) as (parent, base):
            fd = os.open(base, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
                raise ValueError('Not a bounded single-link regular file')
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            if (len(data) != before.st_size or len(data) > limit or
                    (before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                    (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise ValueError('File changed during snapshot')
            return data

    def names(self, directory=''):
        if directory:
            with self.parent(directory + '/placeholder') as (fd, _):
                return os.listdir(fd)
        return os.listdir(self.fd)

    def exists(self, name):
        try:
            with self.parent(name) as (fd, base):
                os.stat(base, dir_fd=fd, follow_symlinks=False)
                return True
        except FileNotFoundError:
            return False

    def publish(self, name, data, *, expected=None, mode=0o644, minimum=RESERVE):
        """Compare and replace inside pinned directories; never follow a target link."""
        with self.parent(name, create=True) as (fd, base):
            reserve(fd, len(data), minimum)
            temporary = '.toddlerbox-' + secrets.token_hex(16)
            out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=fd)
            try:
                with os.fdopen(out, 'wb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                if expected is None:
                    # Atomic no-clobber publication. Never replace even a racing entry.
                    os.link(temporary, base, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                else:
                    # Restrict replacements to a known, single-link regular file.
                    current = self.read(name)
                    if hashlib.sha256(current).hexdigest() != expected:
                        raise ValueError('Destination changed; preserving local file')
                    os.replace(temporary, base, src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=fd)
                    os.fsync(fd)
                except FileNotFoundError:
                    pass


def atomic_json(path, value):
    path = Path(path)
    with SafeTree(path.parent) as tree:
        data = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
        expected = hashlib.sha256(tree.read(path.name, limit=4*1024**2)).hexdigest() if tree.exists(path.name) else None
        tree.publish(path.name, data, expected=expected, mode=0o600, minimum=0)
