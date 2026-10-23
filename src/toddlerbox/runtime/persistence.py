"""Commit a complete file before replacing the previous saved version."""
from __future__ import annotations

import os
import shutil
import stat
import threading
import time
from pathlib import Path
from typing import Callable, List

TEMP_INFIX = ".tmp"
ORPHAN_READ_LIMIT = 64 * 1024 * 1024

_recovered_directories: set[Path] = set()
_recovery_lock = threading.Lock()


class CommitUncertainError(OSError):
    """Replacement is visible, but directory fsync did not confirm durability."""


def has_archive_reserve(directory: Path, expected_bytes: int = 0) -> bool:
    """Leave space for current-document saves; never delete work to make room."""
    return shutil.disk_usage(directory).free - expected_bytes >= 16 * 1024 * 1024


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def temporary_path(path: Path) -> Path:
    # One fixed temporary per target. An interrupted process leaves at most one
    # orphan per target, which recover_orphans() classifies before reuse.
    return path.with_name(f".{path.stem}{TEMP_INFIX}{path.suffix}")


def is_work_name(name: str) -> bool:
    """Visible saved work: never temporaries, dotfiles or quarantined media."""
    return not name.startswith((".", "corrupt-"))


def _write_temporary(temporary: Path, data: bytes) -> None:
    # Buffered writes raise on short writes (ENOSPC, EFBIG, EIO); encoders that
    # write straight to a path cannot, so callers must hand over finished bytes.
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _confirm_directory(path: Path) -> None:
    try:
        sync_directory(path.parent)
    except OSError as error:
        raise CommitUncertainError(
            f"Replacement visible at {path}, but directory sync failed; durability is unconfirmed"
        ) from error


def write_bytes(path: Path, data: bytes) -> None:
    """Before replace, failures preserve the old file; afterwards durability is uncertain."""
    path = Path(path)
    temporary = temporary_path(path)
    try:
        _write_temporary(temporary, data)
        os.replace(temporary, path)
        _confirm_directory(path)
    finally:
        temporary.unlink(missing_ok=True)


def _link_new(source: Path, path: Path) -> Path:
    candidate, counter = path, 1
    while True:
        try:
            os.link(source, candidate, follow_symlinks=False)
            return candidate
        except FileExistsError:
            candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
            counter += 1


def publish_new_bytes(path: Path, data: bytes) -> Path:
    """Publish a new file without ever replacing an existing name; returns the name used."""
    path = Path(path)
    temporary = temporary_path(path)
    try:
        _write_temporary(temporary, data)
        published = _link_new(temporary, path)
        _confirm_directory(published)
        return published
    finally:
        temporary.unlink(missing_ok=True)


def quarantine(path: Path) -> Path:
    """Keep unreadable work for a parent under a corrupt- name; never overwrite."""
    path = Path(path)
    target = _link_new(path, path.with_name(f"corrupt-{time.time_ns()}{path.suffix}"))
    path.unlink()
    sync_directory(path.parent)
    return target


def recover_orphans(directory: Path, *, suffix: str, validate: Callable[[bytes], bool],
                    recovered_dir: Path) -> List[Path]:
    """Classify temporaries left by an earlier process before any write reuses them.

    In-process writers always remove their own temporary, so this runs once per
    directory per process, before that process issues its first write there.
    """
    directory = Path(directory)
    key = directory.resolve()
    with _recovery_lock:
        if key in _recovered_directories:
            return []
        results: List[Path] = []
        if directory.is_dir():
            for temporary in sorted(directory.glob(f".*{TEMP_INFIX}{suffix}")):
                try:
                    info = temporary.lstat()
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode):
                    continue
                try:
                    valid = info.st_size <= ORPHAN_READ_LIMIT and bool(validate(temporary.read_bytes()))
                except Exception:
                    valid = False
                stamp = time.time_ns()
                if valid:
                    target = _link_new(temporary, Path(recovered_dir) / f"recovered-{stamp}{suffix}")
                else:
                    target = _link_new(temporary, directory / f"corrupt-{stamp}{suffix}")
                temporary.unlink()
                sync_directory(target.parent)
                if target.parent != directory:
                    sync_directory(directory)
                results.append(target)
        _recovered_directories.add(key)
        return results
