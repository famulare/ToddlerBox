"""Parent-only setup and candidate lifecycle; no child-writable imports."""
import json
import fcntl
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid

from boot_recovery import STATE, atomic, latest, record, safe, validate, publish_setup

STEPS = ("network", "audio", "input", "recovery", "drive")


def mode(message):
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.bind("\0toddlerbox-maintenance-" + uuid.uuid4().hex)
        client.settimeout(8)
        client.sendto(message.encode(), "/run/toddlerbox-control.sock")
        reply = client.recv(1024)
        if reply != b"OK":
            raise ValueError("Session change refused; inspect parent status")


def guard(root=Path("/"), *, readonly=False, allow_apt=False, allow_recovery=False):
    if os.geteuid() != 0:
        raise ValueError("Parent administrator authentication required")
    if readonly:
        return
    if (root / "run/toddlerbox-system/mode").read_text().strip() != "parent":
        raise ValueError("Use parent mode and parent administrator authentication")
    if not allow_recovery and (root / STATE / "maintenance").exists():
        raise ValueError("Installation/recovery is in progress")
    if not allow_apt and (root / STATE / "apt-maintenance").exists():
        raise ValueError("Complete Ubuntu repair/maintenance first")


def progress(root=Path("/")):
    path = safe(root, STATE / "setup.json")
    if not path.exists():
        return {"version": 1, "checks": {}}
    if path.stat().st_size > 8192:
        raise ValueError("Invalid setup state")
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("checks"), dict):
        raise ValueError("Unsupported setup state")
    if not set(value["checks"]) <= set(STEPS) or any(v not in {"passed", "skipped", "failed"} for v in value["checks"].values()):
        raise ValueError("Invalid setup checks")
    return value


def check(step, result, root=Path("/")):
    guard(root)
    if step not in STEPS or result not in {"passed", "skipped", "failed"}:
        raise ValueError("Unknown setup check")
    if step == "recovery" and result == "passed" and not (root / "run/toddlerbox-system/setup-recovery-observed").exists():
        raise ValueError("Run the supervised child test and escape back to parent login first")
    value = progress(root)
    value["checks"][step] = result
    record(safe(root, STATE / "setup.json"), value)


def finish(root=Path("/")):
    guard(root)
    value = progress(root)
    if set(value["checks"]) != set(STEPS) or value["checks"]["recovery"] != "passed":
        raise ValueError("Complete the checks and confirm authenticated parent recovery first")
    atomic(safe(root, STATE / "setup-complete"), b"setup-v1\n")
    publish_setup(root)


@contextmanager
def maintenance_lock(root=Path("/")):
    directory = safe(root, STATE / "updates")
    directory.mkdir(mode=0o700, exist_ok=True)
    with safe(root, STATE / "updates/lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def _candidate_entry(root):
    item = latest(root)
    if item and item[1]["status"] not in {"pending", "accepted", "rolled-back"}:
        raise ValueError("Update/recovery state prevents child startup")
    if item and item[1]["status"] == "pending":
        job, value = item
        validate(root, job, value)
        if value.get("attempts", 0) >= 2:
            raise ValueError("Candidate test budget exhausted; reboot to recover")
        value["attempts"] = value.get("attempts", 0) + 1
        value["observed"] = False
        record(job / "state.json", value)


def observed(root=Path("/")):
    if (root / "run/toddlerbox-system/setup-test").exists():
        atomic(root / "run/toddlerbox-system/setup-test-observed", b"frames\n")
    item = latest(root)
    if item and item[1]["status"] == "pending" and not item[1].get("observed"):
        job, value = item
        value["observed"] = True
        record(job / "state.json", value)


def invalidate_observation(root=Path("/")):
    (root / "run/toddlerbox-system/setup-test-observed").unlink(missing_ok=True)
    item = latest(root)
    if item and item[1]["status"] == "pending":
        job, value = item
        value["observed"] = False
        record(job / "state.json", value)


def needs_candidate_recovery(recovered, intentional, root=Path("/")):
    if not recovered or intentional or any((root / STATE / name).exists() for name in ("maintenance", "recovery-error")):
        return False
    item = latest(root)
    return bool(item and item[1]["status"] == "pending")


def accept(root=Path("/")):
    with maintenance_lock(root):
        guard(root)
        item = latest(root)
        if not item or item[1]["status"] != "pending" or not item[1].get("observed"):
            raise ValueError("Test the candidate child session for at least ten seconds, then return to parent mode")
        job, value = item
        validate(root, job, value)
        value["status"] = "accepted"
        value["accepted_at"] = int(time.time())
        record(job / "state.json", value)


def command(args, *, timeout=30):
    return subprocess.run(args, check=True, timeout=timeout, capture_output=True, text=True)
