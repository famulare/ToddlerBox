"""Commit a complete file before replacing the previous saved version."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable


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


def atomic_write(path: Path, write: Callable[[Path], None]) -> None:
    """Before replace, failures preserve the old file; afterwards durability is uncertain."""
    # Preserve the extension for image encoders. Single app process owns this file.
    temporary = path.with_name(f".{path.stem}.tmp{path.suffix}")
    try:
        write(temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            sync_directory(path.parent)
        except OSError as error:
            raise CommitUncertainError(
                f"Replacement visible at {path}, but directory sync failed; durability is unconfirmed"
            ) from error
    finally:
        temporary.unlink(missing_ok=True)


def write_bytes(path: Path, data: bytes) -> None:
    atomic_write(path, lambda temporary: temporary.write_bytes(data))
