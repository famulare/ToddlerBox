#!/usr/bin/python3
"""Root-owned session controller. No imports from the child-writable data tree."""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path
import pwd
import selectors
import socket
import struct
import subprocess
import time

STATE = Path("/var/lib/toddlerbox-system")
RUNTIME = Path("/run/toddlerbox-system")
HEALTH = "/run/toddlerbox-health.sock"
CONTROL = "/run/toddlerbox-control.sock"
INPUT_EVENT = struct.Struct("llHHi")  # Linux input_event, native timeval
CTRL, ALT, HOME = {29, 97}, {56, 100}, 102


def durable_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


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


def restart_gdm() -> None:
    # Give the app a bounded chance to save before terminating the graphical seat.
    subprocess.run(["pkill", "-TERM", "-u", "toddlerbox", "-fx", ".venv/bin/python -m toddlerbox.launcher"],
                   check=False)
    time.sleep(2)
    # A SIGSTOPed/frozen app cannot process TERM. Bound shutdown before GDM restart.
    subprocess.run(["pkill", "-KILL", "-u", "toddlerbox", "-fx", ".venv/bin/python -m toddlerbox.launcher"],
                   check=False)
    environment = dict(os.environ)
    environment.pop("NOTIFY_SOCKET", None)
    subprocess.run(["systemctl", "restart", "--no-block", "gdm3.service"],
                   env=environment, check=True)


def bind_socket(path: str, mode: int, uid: int = 0) -> socket.socket:
    Path(path).unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    server.bind(path)
    os.chown(path, uid, 0)
    os.chmod(path, mode)
    server.setblocking(False)
    return server


def sender_uid(ancillary: list) -> int | None:
    for level, kind, data in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS:
            return struct.unpack("3i", data)[1]
    return None


def rollback() -> None:
    root = Path("/opt/toddlerbox")
    current = (root / "current").resolve(strict=True)
    previous = (root / "previous").resolve(strict=True)
    if previous.parent != root / "releases" or current.parent != root / "releases":
        raise ValueError("release symlink outside releases directory")
    for name, target in [("current", previous), ("previous", current)]:
        temporary = root / f".{name}.next"
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(target)
        os.replace(temporary, root / name)


def main() -> None:
    STATE.mkdir(mode=0o700, exist_ok=True)
    RUNTIME.mkdir(mode=0o755, exist_ok=True)
    child_uid = pwd.getpwnam("toddlerbox").pw_uid
    cmdline = Path("/proc/cmdline").read_text().split()
    mode = "parent" if (STATE / "parent-mode").exists() or "toddlerbox.parent=1" in cmdline else "child"
    # A controller crash itself must fail into parent mode on its next start.
    if (RUNTIME / "controller-started").exists():
        mode = "parent"
    (RUNTIME / "controller-started").touch()
    configure_gdm(mode)
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
            (STATE / "parent-mode").unlink(missing_ok=True)
        configure_gdm(target)
        mode = target
        watchdog = Watchdog(time.monotonic())
        restart_gdm()

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
                message, ancillary, _flags, _address = key.fileobj.recvmsg(128, socket.CMSG_SPACE(12))
                uid = sender_uid(ancillary)
                if key.data == "health" and uid == child_uid and mode == "child":
                    if message == b"frame":
                        watchdog.frame(time.monotonic())
                elif key.data == "control" and uid == 0:
                    reply = b"OK"
                    if message in {b"parent", b"child"}:
                        transition(message.decode(), "parent command")
                    elif message == b"rollback":
                        try:
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
                restart_gdm()
        status = {"mode": mode, "restarts": watchdog.restarts,
                  "seen_frame": watchdog.seen_frame}
        # /run is a tmpfs: diagnostic status must not generate disk writes each frame.
        (RUNTIME / "status.json").write_text(json.dumps(status) + "\n")


if __name__ == "__main__":
    main()
