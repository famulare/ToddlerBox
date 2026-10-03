"""Explicit parent maintenance; standard-library-only, fixed system destinations.

The first update is a checksum-verified executable zip; subsequent updates can
use the root-owned toddlerbox-update command installed by it. No network polling.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile

FILES = {
    "controller.py": ("usr/local/lib/toddlerbox-system/controller.py", 0o644),
    "toddlerbox-session": ("usr/local/libexec/toddlerbox-session", 0o755),
    "toddlerbox-volume": ("usr/local/libexec/toddlerbox-volume", 0o755),
    "toddlerbox-cage": ("usr/local/libexec/toddlerbox-cage", 0o755),
    "update_bundle.py": ("usr/local/lib/toddlerbox-system/update_bundle.py", 0o644),
    "toddlerbox-update": ("usr/local/sbin/toddlerbox-update", 0o755),
}
PACKAGES = ["pipewire", "pipewire-pulse", "wireplumber"]
STATE = "var/lib/toddlerbox-system/updates"
APP = "opt/toddlerbox"
SERVICE = "toddlerbox-controller.service"


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def digest_ok(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def replace(source, target, mode):
    # All destinations are fixed, root-owned paths; never follow a target link.
    fd, name = tempfile.mkstemp(prefix=".tbx-update-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
            shutil.copyfileobj(inp, out)
            os.fchmod(out.fileno(), mode)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, target)
        sync_dir(target.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def record(path, value):
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        source = Path(directory) / "record"
        source.write_text(json.dumps(value, sort_keys=True) + "\n")
        replace(source, path, 0o600)


def safe_path(root, relative):
    target = root / relative
    for path in [target, *target.parents]:
        if path == root.parent:
            break
        if path.is_symlink():
            raise ValueError(f"Refusing symlink in maintenance path: {path}")
    if target.exists() and not (target.is_file() or target.is_dir()):
        raise ValueError("Unsupported maintenance path type")
    return target


@contextmanager
def lock(state):
    with (state / "lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def guard(root):
    if os.geteuid() != 0:
        raise ValueError("Run with sudo from the parent account.")
    if (root / "run/toddlerbox-system/mode").read_text().strip() != "parent":
        raise ValueError("Enter parent mode and save parent desktop work first.")
    info = dict(line.split("=", 1) for line in (root / "etc/os-release").read_text().splitlines()
                if "=" in line)
    if info.get("ID", "").strip('"') != "ubuntu" or info.get("VERSION_ID", "").strip('"') != "24.04" or platform.machine() != "x86_64":
        raise ValueError("This bundle requires Ubuntu 24.04 x86-64.")


def stage_bundle(bundle, digest, stage):
    if not digest_ok(digest):
        raise ValueError("Expected SHA-256 must be 64 lowercase hex characters.")
    # Pin the verified descriptor, so pathname substitution cannot change inputs.
    with bundle.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
            raise ValueError("Bundle checksum mismatch; nothing installed.")
        handle.seek(0)
        with zipfile.ZipFile(handle) as archive:
            entries = archive.infolist()
            names = [item.filename for item in entries]
            if len(names) != len(set(names)) or len(names) > 12:
                raise ValueError("Duplicate or excessive bundle entries")
            for item in entries:
                if item.is_dir() or stat.S_IFMT(item.external_attr >> 16) not in (0, stat.S_IFREG):
                    raise ValueError("Bundle entries must be regular files")
                if item.file_size > 1024 ** 3:
                    raise ValueError("Bundle entry too large")
            if archive.getinfo("manifest.json").file_size > 16384:
                raise ValueError("Manifest too large")
            manifest = json.loads(archive.read("manifest.json"))
            if set(manifest) != {"format", "source", "files", "app"} or manifest["format"] != 1:
                raise ValueError("Unsupported update format")
            files = manifest["files"]
            if not isinstance(files, dict) or not set(files) <= FILES.keys():
                raise ValueError("Unsupported system destination")
            allowed = {"__main__.py", "update_bundle.py", "manifest.json"} | {"payload/" + name for name in files}
            if manifest["app"] is not None:
                allowed.add("app.tar.gz")
            if set(names) != allowed:
                raise ValueError("Unexpected bundle path")
            required = sum(item.file_size for item in entries) * 3 + 256 * 1024 ** 2
            if shutil.disk_usage(stage).free < required:
                raise OSError("Insufficient disk reserve for staging and rollback")
            inputs = {"payload/" + key: value for key, value in files.items()}
            if manifest["app"] is not None:
                inputs["app.tar.gz"] = manifest["app"]
            for name, expected in inputs.items():
                if not digest_ok(expected):
                    raise ValueError("Invalid payload checksum")
                destination = stage / Path(name).name
                with archive.open(name) as inp, destination.open("wb") as out:
                    shutil.copyfileobj(inp, out)
                if sha(destination) != expected:
                    raise ValueError("Payload checksum mismatch")
    return manifest


def app_links(root):
    base = root / APP
    result = {}
    for name in ("current", "previous"):
        path = base / name
        if not path.exists() and not path.is_symlink():
            result[name] = None
            continue
        target = path.resolve(strict=True)
        if not path.is_symlink() or target.parent != base / "releases" or not target.is_dir():
            raise ValueError("Unsafe app release link")
        result[name] = target.name
    return result


def restore(root, job, state):
    # Validate *all* backup bytes before replacing anything.
    for name, old in state["old_files"].items():
        if name not in FILES:
            raise ValueError("Unknown rollback destination")
        safe_path(root, FILES[name][0])
        if old is not None and sha(job / name) != old["sha256"]:
            raise ValueError("Rollback backup checksum mismatch")
    for name, old in state["old_files"].items():
        target = root / FILES[name][0]
        if old is None:
            target.unlink(missing_ok=True)
            sync_dir(target.parent)
        else:
            replace(job / name, target, old["mode"])
    if state["app_changed"]:
        base = root / APP
        for name, release in state["old_links"].items():
            if name not in {"current", "previous"}:
                raise ValueError("Invalid rollback link")
            if release is None:
                (base / name).unlink(missing_ok=True)
            else:
                if Path(release).name != release or not (base / "releases" / release).is_dir():
                    raise ValueError("Previous app release is unavailable")
                temporary = base / (".update-" + name)
                temporary.unlink(missing_ok=True)
                temporary.symlink_to("releases/" + release)
                os.replace(temporary, base / name)
            sync_dir(base)
    state["status"] = "rolled-back"
    record(job / "state.json", state)


def command(args):
    subprocess.run(args, check=True, timeout=900)


def restart():
    command(["systemctl", "start", "--no-block", SERVICE])


def latest(state):
    marker = state / "latest.json"
    if not marker.exists():
        return None
    identifier = json.loads(marker.read_text())["job"]
    if len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
        raise ValueError("Invalid update journal")
    job = state / identifier
    return job, json.loads((job / "state.json").read_text())


def run(bundle=None, digest=None, *, rollback=False, root=Path("/")):
    guard(root)
    directory = safe_path(root, STATE)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock(directory):
        previous = latest(directory)
        if rollback:
            if not previous or previous[1]["status"] == "rolled-back":
                raise ValueError("No pending or applied update to roll back.")
            command(["systemctl", "stop", SERVICE])
            try:
                restore(root, *previous)
            finally:
                restart()
            return "Previous controls/app restored; audio packages retained. Return to parent login."
        if previous and previous[1]["status"] == "applying":
            raise ValueError("Interrupted update: run toddlerbox-update --rollback first.")
        with tempfile.TemporaryDirectory(dir=directory, prefix=".stage-") as temporary:
            stage = Path(temporary)
            manifest = stage_bundle(Path(bundle), digest, stage)
            if previous and previous[1]["status"] == "applied" and previous[1]["bundle"] == digest:
                return "This update is already installed; rollback remains available."
            for name in manifest["files"]:
                target = safe_path(root, FILES[name][0])
                if target.exists() and not target.is_file():
                    raise ValueError("System destination is not a regular file")
                if not target.parent.is_dir():
                    raise ValueError("Required system directory is missing")
            # Package operations precede file replacement. A network/apt failure
            # does not change controller/app files or discard the last rollback.
            command(["apt-get", "update"])
            command(["apt-get", "install", "-y", "--no-install-recommends", *PACKAGES])
            if "toddlerbox-cage" in manifest["files"]:
                libraries = subprocess.run(["ldd", str(stage / "toddlerbox-cage")], check=True,
                                           capture_output=True, text=True, timeout=10).stdout
                if "not found" in libraries:
                    raise ValueError("Compositor libraries are unavailable")
            # Apt may take minutes; refuse if the parent switched sessions meanwhile.
            guard(root)
            job = directory / uuid.uuid4().hex
            job.mkdir(mode=0o700)
            state = {"bundle": digest, "source": manifest["source"], "status": "applying",
                     "old_files": {}, "old_links": app_links(root),
                     "app_changed": manifest["app"] is not None}
            for name in manifest["files"]:
                target = root / FILES[name][0]
                if target.exists():
                    replace(target, job / name, stat.S_IMODE(target.stat().st_mode))
                    state["old_files"][name] = {"sha256": sha(job / name), "mode": stat.S_IMODE(target.stat().st_mode)}
                else:
                    state["old_files"][name] = None
            record(job / "state.json", state)
            record(directory / "latest.json", {"job": job.name})
            command(["systemctl", "stop", SERVICE])
            try:
                for name in manifest["files"]:
                    destination, mode = FILES[name]
                    replace(stage / name, root / destination, mode)
                if manifest["app"] is not None:
                    command([str(root / "usr/local/sbin/toddlerbox-install-release"),
                             str(stage / "app.tar.gz"), manifest["app"]])
                state["status"] = "applied"
                record(job / "state.json", state)
            except BaseException:
                restore(root, job, state)
                raise
            finally:
                restart()
    return "Update installed; backups retained. Return to parent login, then Start ToddlerBox."


def main():
    parser = argparse.ArgumentParser(description="Explicit ToddlerBox update; save parent desktop work first.")
    parser.add_argument("bundle", nargs="?")
    parser.add_argument("sha256", nargs="?")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--sha256", dest="self_digest", help="Bootstrap executable zip checksum")
    args = parser.parse_args()
    if args.self_digest:
        args.bundle, args.sha256 = sys.argv[0], args.self_digest
    if not args.rollback and (not args.bundle or not args.sha256):
        parser.error("Supply BUNDLE SHA256, or --rollback.")
    try:
        print(run(args.bundle, args.sha256, rollback=args.rollback), flush=True)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        sys.exit(f"Update stopped: {error}. Child work and private configuration were not replaced.")


if __name__ == "__main__":
    main()
