"""Commit a complete file before replacing the previous saved version."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, write: Callable[[Path], None]) -> None:
    # Preserve the extension for image encoders. Single app process owns this file.
    temporary = path.with_name(f".{path.stem}.tmp{path.suffix}")
    try:
        write(temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def write_bytes(path: Path, data: bytes) -> None:
    atomic_write(path, lambda temporary: temporary.write_bytes(data))
