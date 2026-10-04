"""Keep the one interpreter link accepted by resident release installers."""
from pathlib import Path
import os
import sys


def normalize(venv: Path) -> None:
    binary = venv / "bin"
    canonical = binary / "python"
    if not canonical.is_symlink() or os.readlink(canonical) != "/usr/bin/python3":
        raise ValueError("Unexpected canonical system interpreter")
    aliases = [binary / "python3", binary / "python3.12"]
    for alias in aliases:
        if not alias.is_symlink() or os.readlink(alias) != "python":
            raise ValueError("Unexpected interpreter alias")
    # Entry points must use the canonical executable before aliases are removed.
    for path in binary.iterdir():
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                first = stream.readline(4096).strip()
            if first.startswith(b"#!") and any(str(alias).encode() in first for alias in aliases):
                raise ValueError("Entry point requires an interpreter alias")
    for alias in aliases:
        alias.unlink()


if __name__ == "__main__":
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Pinned Ubuntu Python 3.12 required")
    normalize(Path(sys.argv[1]))
