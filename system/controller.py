#!/usr/bin/python3
"""Root-owned session controller. No imports from the child-writable data tree."""
from __future__ import annotations

import glob
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import pwd
import selectors
import signal
import socket
import struct
import subprocess
import time

STATE = Path("/var/lib/toddlerbox-system")
RUNTIME = Path("/run/toddlerbox-system")
HEALTH = "/run/toddlerbox-health.sock"
CONTROL = "/run/toddlerbox-control.sock"
RELEASE_ROOT = Path("/opt/toddlerbox")
DATA_SCHEMA = {"version": 1, "typing": 1, "paint": 1}
INPUT_EVENT = struct.Struct("llHHi")  # Linux input_event, native timeval
CTRL, ALT, HOME = {29, 97}, {56, 100}, 102


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


class Watchdog:
    """Retries are a per-child-mode budget, never reset by intermittent frames."""
    def __init__(self, now: float, *, startup: float = 90, timeout: float = 20,
                 max_restarts: int = 3) -> None:
        self.startup, self.timeout, self.max_restarts = startup, timeout, max_restarts
        self.deadline = now + startup
        self.restarts = 0
        self.seen_frame = False

    def frame(self, now: float) -> None:
        self.seen_frame = True
        self.deadline = now + self.timeout

    def check(self, now: float) -> str | None:
        if now < self.deadline:
            return None
        if self.restarts >= self.max_restarts:
            return "parent"
        self.restarts += 1
        self.deadline = now + self.startup
        self.seen_frame = False
        return "restart"


class EscapeChord:
    def __init__(self) -> None:
        self.keys: dict[int, set[int]] = {}
        self.since: float | None = None

    def event(self, fd: int, code: int, value: int) -> None:
        keys = self.keys.setdefault(fd, set())
        if value == 0:
            keys.discard(code)
        elif value == 1:
            keys.add(code)

    def held(self, now: float) -> bool:
        # Require all keys on the same keyboard; unplugged keys cannot latch it.
        active = any(keys & CTRL and keys & ALT and HOME in keys
                     for keys in self.keys.values())
        if not active:
            self.since = None
            return False
        if self.since is None:
            self.since = now
        return now - self.since >= 2


def configure_gdm(mode: str) -> None:
    text = "[daemon]\n"
    if mode == "child":
        text += "AutomaticLoginEnable=true\nAutomaticLogin=toddlerbox\n"
    else:
        text += "AutomaticLoginEnable=false\n"
    durable_text(RUNTIME / "gdm.conf", text)
    durable_text(RUNTIME / "mode", mode + "\n")


def launcher_processes(child_uid: int) -> dict[int, int]:
    """Pin process identity before inspecting argv; a reused PID is never signalled."""
    processes = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        pidfd = None
        try:
            pid = int(path.name)
            pidfd = os.pidfd_open(pid)
            if path.stat().st_uid != child_uid:
                continue
            args = (path / "cmdline").read_bytes().split(b"\0")
            if len(args) < 3 or args[1:3] != [b"-m", b"toddlerbox.launcher"]:
                continue
            processes[pid] = pidfd
            pidfd = None
        except OSError:
            # Exiting processes and unreadable /proc entries need no fallback kill.
            continue
        finally:
            if pidfd is not None:
                os.close(pidfd)
    return processes


def stop_launchers(health: socket.socket, child_uid: int, *, grace: float = 5) -> None:
    """Wait for cleanup acknowledgement or exit, with one bounded save deadline."""
    processes = launcher_processes(child_uid)
    pending = set(processes)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(health, selectors.EVENT_READ, None)
            for pid, pidfd in processes.items():
                selector.register(pidfd, selectors.EVENT_READ, pid)
                try:
                    signal.pidfd_send_signal(pidfd, signal.SIGTERM)
                except ProcessLookupError:
                    pending.discard(pid)
            deadline = time.monotonic() + grace
            while pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                for key, _mask in selector.select(remaining):
                    if key.data is not None:
                        pending.discard(key.data)
                        selector.unregister(key.fd)
                    else:
                        try:
                            message, ancillary, _flags, _address = health.recvmsg(128, socket.CMSG_SPACE(12))
                        except BlockingIOError:
                            continue
                        credentials = sender_credentials(ancillary)
                        if (credentials and credentials[1] == child_uid
                                and message == b"shutdown-complete"):
                            pending.discard(credentials[0])
            for pid in pending:
                try:
                    signal.pidfd_send_signal(processes[pid], signal.SIGKILL)
                except ProcessLookupError:
                    pass
    finally:
        for pidfd in processes.values():
            os.close(pidfd)


def restart_gdm(health: socket.socket, child_uid: int) -> None:
    stop_launchers(health, child_uid)
    environment = dict(os.environ)
    environment.pop("NOTIFY_SOCKET", None)
    subprocess.run(["systemctl", "restart", "--no-block", "gdm3.service"],
                   env=environment, check=True, timeout=2)


def bind_socket(path: str, mode: int, uid: int = 0) -> socket.socket:
    Path(path).unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    server.bind(path)
    os.chown(path, uid, 0)
    os.chmod(path, mode)
    server.setblocking(False)
    return server


def sender_credentials(ancillary: list) -> tuple[int, int, int] | None:
    for level, kind, data in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS:
            if len(data) == 12:
                return struct.unpack("3i", data)
    return None


def sender_uid(ancillary: list) -> int | None:
    credentials = sender_credentials(ancillary)
    return credentials[1] if credentials else None


@contextmanager
def release_lock(root: Path):
    with (root / ".release.lock").open("a") as handle:
        # Parent recovery must never wait indefinitely for an installer.
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def release_target(root: Path, name: str) -> Path:
    target = (root / name).resolve(strict=True)
    if target.parent != root / "releases" or not target.is_dir():
        raise ValueError("release symlink outside releases directory")
    return target


def data_schema(release: Path, *, legacy: bool = True) -> dict:
    marker = release / "data-schema.json"
    if not marker.exists() and legacy:
        # Only already-installed, pre-marker releases get the original v1 schema.
        return DATA_SCHEMA.copy()
    record = json.loads(marker.read_text())
    if (not isinstance(record, dict) or record.keys() != DATA_SCHEMA.keys()
            or any(type(value) is not int or value < 1 for value in record.values())
            or record["version"] != 1):
        raise ValueError("invalid release data-schema.json")
    return record


def replace_release_link(root: Path, name: str, target: Path) -> None:
    temporary = root / f".{name}.next"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, root / name)
    sync_directory(root)


def rollback(root: Path = RELEASE_ROOT) -> None:
    with release_lock(root):
        current = release_target(root, "current")
        previous = release_target(root, "previous")
        if current == previous:
            raise ValueError("previous release is already current")
        if data_schema(current) != data_schema(previous):
            raise ValueError("release data schemas differ; restore a compatible data backup first")
        # Keep the fallback identifiable even if power fails during the switch.
        # Rollback is one durable replacement, not a two-link swap/toggle.
        replace_release_link(root, "current", previous)


def startup_mode() -> tuple[str, bool]:
    cmdline = Path("/proc/cmdline").read_text().split()
    recovered = (RUNTIME / "controller-started").exists()
    mode = "parent" if recovered or (STATE / "parent-mode").exists() or "toddlerbox.parent=1" in cmdline else "child"
    if recovered:
        try:
            durable_text(STATE / "parent-mode", "controller restarted\n")
        except OSError as error:
            print(f"Cannot persist recovery latch: {error}", flush=True)
    (RUNTIME / "controller-started").touch()
    configure_gdm(mode)
    return mode, recovered


def main() -> None:
    STATE.mkdir(mode=0o700, exist_ok=True)
    RUNTIME.mkdir(mode=0o755, exist_ok=True)
    child_uid = pwd.getpwnam("toddlerbox").pw_uid
    mode, recovered = startup_mode()
    selector = selectors.DefaultSelector()
    health = bind_socket(HEALTH, 0o600, child_uid)
    control = bind_socket(CONTROL, 0o600)
    selector.register(health, selectors.EVENT_READ, "health")
    selector.register(control, selectors.EVENT_READ, "control")
    chord = EscapeChord()
    devices: dict[str, int] = {}
    watchdog = Watchdog(time.monotonic())
    next_scan = 0.0
    next_notify = 0.0
    print(f"ToddlerBox controller ready: {mode}", flush=True)
    # Type=notify orders GDM after socket and mode configuration are ready.
    address = os.environ.get("NOTIFY_SOCKET")
    if address:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notify:
            notify.sendto(b"READY=1", address.replace("@", "\0", 1) if address.startswith("@") else address)
    if recovered:
        # READY first avoids ordering deadlock with GDM's After=controller.
        # Merely changing autologin does not end an already-running child seat.
        restart_gdm(health, child_uid)

    def transition(target: str, reason: str) -> None:
        nonlocal mode, watchdog
        print(f"ToddlerBox mode={target} reason={reason}", flush=True)
        if target == "parent":
            # Remain recoverable across reboot, even if runtime remains broken.
            try:
                durable_text(STATE / "parent-mode", reason + "\n")
            except OSError as error:
                print(f"Cannot persist recovery latch: {error}", flush=True)
        else:
            with release_lock(RELEASE_ROOT):
                (STATE / "parent-mode").unlink(missing_ok=True)
                sync_directory(STATE)
                configure_gdm(target)
        if target == "parent":
            configure_gdm(target)
        mode = target
        watchdog = Watchdog(time.monotonic())
        restart_gdm(health, child_uid)

    while True:
        now = time.monotonic()
        if address and now >= next_notify:
            next_notify = now + 2
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notify:
                notify.sendto(b"WATCHDOG=1", address.replace("@", "\0", 1) if address.startswith("@") else address)
        if now >= next_scan:
            next_scan = now + 2
            for name in glob.glob("/dev/input/event*"):
                if name in devices:
                    continue
                try:
                    fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK)
                    selector.register(fd, selectors.EVENT_READ, name)
                    devices[name] = fd
                except OSError:
                    continue
        for key, _mask in selector.select(0.1):
            if key.data in {"health", "control"}:
                try:
                    message, ancillary, _flags, _address = key.fileobj.recvmsg(128, socket.CMSG_SPACE(12))
                except BlockingIOError:
                    # A preceding control event can drain health during shutdown,
                    # leaving a stale readability notification in this batch.
                    continue
                uid = sender_uid(ancillary)
                if key.data == "health" and uid == child_uid and mode == "child":
                    if message == b"frame":
                        watchdog.frame(time.monotonic())
                elif key.data == "control" and uid == 0:
                    reply = b"OK"
                    if message in {b"parent", b"child"}:
                        try:
                            transition(message.decode(), "parent command")
                        except BlockingIOError as error:
                            reply = f"ERROR: {error}".encode()
                    elif message == b"rollback":
                        try:
                            if mode != "parent":
                                raise ValueError("enter parent mode before rollback")
                            rollback()
                            transition("parent", "release rolled back; inspect then start child mode")
                        except (OSError, ValueError) as error:
                            print(f"Rollback refused: {error}", flush=True)
                            reply = f"ERROR: {error}".encode()
                    else:
                        reply = b"ERROR: unknown command"
                    if _address:
                        try:
                            control.sendto(reply, _address)
                        except OSError:
                            pass
            else:
                try:
                    data = os.read(key.fd, INPUT_EVENT.size * 64)
                    if not data:
                        raise OSError("input device disconnected")
                    for _sec, _usec, kind, code, value in INPUT_EVENT.iter_unpack(data):
                        if kind == 1:  # EV_KEY
                            chord.event(key.fd, code, value)
                        elif kind == 0 and code == 3:  # SYN_DROPPED: discard stale keys
                            chord.keys.pop(key.fd, None)
                except OSError:
                    selector.unregister(key.fd)
                    os.close(key.fd)
                    devices.pop(key.data, None)
                    chord.keys.pop(key.fd, None)
        if mode == "child":
            if chord.held(time.monotonic()):
                transition("parent", "Ctrl+Alt+Home held for two seconds")
                continue
            action = watchdog.check(time.monotonic())
            if action == "parent":
                transition("parent", "watchdog restart budget exhausted")
            elif action == "restart":
                print(f"Watchdog restarting GDM, attempt {watchdog.restarts}/{watchdog.max_restarts}", flush=True)
                restart_gdm(health, child_uid)
        status = {"mode": mode, "restarts": watchdog.restarts,
                  "seen_frame": watchdog.seen_frame}
        # /run is a tmpfs: diagnostic status must not generate disk writes each frame.
        (RUNTIME / "status.json").write_text(json.dumps(status) + "\n")


if __name__ == "__main__":
    main()
