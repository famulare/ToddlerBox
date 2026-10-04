"""Resident recovery protocol v1. Never replace this file in an ordinary bundle.

No imports from the candidate controller/updater. All restore destinations are
compiled here; journals cannot introduce commands or arbitrary paths.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

DESTINATIONS = {
    "controller.py": ("usr/local/lib/toddlerbox-system/controller.py", 0o644),
    "toddlerbox-session": ("usr/local/libexec/toddlerbox-session", 0o755),
    "toddlerbox-volume": ("usr/local/libexec/toddlerbox-volume", 0o755),
    "toddlerbox-cage": ("usr/local/libexec/toddlerbox-cage", 0o755),
    "update_bundle.py": ("usr/local/lib/toddlerbox-system/update_bundle.py", 0o644),
    "toddlerbox-update": ("usr/local/sbin/toddlerbox-update", 0o755),
    "toddlerbox-install-release": ("usr/local/sbin/toddlerbox-install-release", 0o755),
    "appliance.py": ("usr/local/lib/toddlerbox-system/appliance.py", 0o644),
    "release_client.py": ("usr/local/lib/toddlerbox-system/release_client.py", 0o644),
    "toddlerbox-maintenance": ("usr/local/sbin/toddlerbox-maintenance", 0o755),
    "release-public-key.pem": ("etc/toddlerbox/release-public-key.pem", 0o644),
}
STATE = Path("var/lib/toddlerbox-system")


def safe(root, relative):
    path = root / relative
    for parent in (path, *path.parents):
        if parent == root.parent:
            break
        if parent.is_symlink():
            raise ValueError("Symlink in recovery path")
        if parent.exists():
            info = parent.stat()
            if root == Path("/") and (info.st_uid != 0 or info.st_mode & 0o022):
                raise ValueError("Recovery path must be root-owned and not writable by others")
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError("Unsafe recovery path")
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise ValueError("Hardlinked recovery file")
    return path


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path, content, mode=0o600):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".recovery-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            os.fchmod(handle.fileno(), mode)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        fsync_dir(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def record(path, value):
    atomic(path, (json.dumps(value, sort_keys=True) + "\n").encode())


def read(path):
    if path.stat().st_size > 65536:
        raise ValueError("Oversized recovery state")
    return json.loads(path.read_text())


def latest(root):
    directory = safe(root, STATE / "updates")
    marker = safe(root, STATE / "updates/latest.json")
    if not marker.exists():
        return None
    identifier = read(marker)["job"]
    if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
        raise ValueError("Invalid journal identifier")
    job = safe(root, STATE / "updates" / identifier)
    return job, read(safe(root, STATE / "updates" / identifier / "state.json"))


def validate(root, job, value):
    if value.get("protocol") != 1 or value.get("status") not in {"applying", "pending", "accepted", "restoring"} or type(value.get("app_changed")) is not bool:
        raise ValueError("Unsupported recovery journal")
    files = value["old_files"]
    if not isinstance(files, dict) or not set(files) <= DESTINATIONS.keys():
        raise ValueError("Invalid restore destination")
    if type(value.get("attempts")) is not int or not 0 <= value["attempts"] <= 2 or type(value.get("observed")) is not bool:
        raise ValueError("Invalid candidate state")
    for name, old in files.items():
        safe(root, DESTINATIONS[name][0])
        if old is not None:
            source = safe(root, job.relative_to(root) / name)
            if source.stat().st_size > 16 * 1024 ** 2:
                raise ValueError("Oversized system backup")
            with source.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            if digest != old["sha256"] or old["mode"] != DESTINATIONS[name][1]:
                raise ValueError("Invalid backup")
    links = value["old_links"]
    if set(links) != {"current", "previous"}:
        raise ValueError("Invalid release links")
    base = safe(root, "opt/toddlerbox")
    for release in links.values():
        if release is not None:
            if not isinstance(release, str) or Path(release).name != release or release in {".", ".."}:
                raise ValueError("Unsafe release name")
            if not safe(root, Path("opt/toddlerbox/releases") / release).is_dir():
                raise ValueError("Missing previous release")


def restore(root, job, value):
    validate(root, job, value)
    files = value["old_files"]
    atomic(root / STATE / "parent-mode", b"Restoring previous release\n")
    atomic(root / STATE / "maintenance", b"restoring\n")
    value["status"] = "restoring"
    record(job / "state.json", value)
    for name, old in files.items():
        target = root / DESTINATIONS[name][0]
        if old is None:
            target.unlink(missing_ok=True)
            fsync_dir(target.parent)
        else:
            atomic(target, (job / name).read_bytes(), DESTINATIONS[name][1])
    if value["app_changed"]:
        base = root / "opt/toddlerbox"
        links = value["old_links"]
        for name, release in links.items():
            target = base / name
            if release is None:
                target.unlink(missing_ok=True)
            else:
                temporary = base / (".recover-" + name)
                temporary.unlink(missing_ok=True)
                temporary.symlink_to("releases/" + release)
                os.replace(temporary, target)
            fsync_dir(base)
    value["status"] = "rolled-back"
    record(job / "state.json", value)


def gate(root=Path("/"), *, failure=False):
    state = safe(root, STATE)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        item = latest(root)
        maintenance = safe(root, STATE / "maintenance")
        if maintenance.exists() and item is None:
            raise ValueError("Missing required journal")
        if item:
            job, value = item
            if value.get("protocol") != 1:
                raise ValueError("Unsupported journal protocol")
            status = value["status"]
            if status not in {"applying", "restoring", "pending", "accepted", "rolled-back"}:
                raise ValueError("Unknown recovery state")
            if status != "rolled-back":
                validate(root, job, value)
            if status in {"applying", "restoring"} or (failure and status == "pending"):
                restore(root, job, value)
                atomic(state / "parent-mode", b"Update restored; inspect before child use\n")
            elif status == "pending":
                if value.get("attempts", 0) >= 2:
                    restore(root, job, value)
                    atomic(state / "parent-mode", b"Unconfirmed candidate exceeded test budget\n")
                else:
                    atomic(state / "parent-mode", b"Candidate awaits parent test and acceptance\n")
        maintenance.unlink(missing_ok=True)
        safe(root, STATE / "recovery-error").unlink(missing_ok=True)
        fsync_dir(state)
        return True
    except (OSError, ValueError, KeyError, TypeError) as error:
        atomic(state / "parent-mode", b"Boot recovery needs parent repair\n")
        # Error category only: do not echo paths or malformed state contents.
        atomic(state / "recovery-error", type(error).__name__.encode() + b"\n")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--failure", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Root required")
    state = Path("/") / STATE
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = safe(Path("/"), STATE / "updates")
    directory.mkdir(mode=0o700, exist_ok=True)
    with (directory / "lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not gate(failure=args.failure):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
