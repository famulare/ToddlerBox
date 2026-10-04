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
import select
import re
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


class ObservationWindow:
    """Ten seconds of processed frames within one uninterrupted session."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.first = self.last = None
        self.confirmed = False
        self.generation = None

    def frame(self, now, *, generation=None):
        if self.generation != generation:
            self.reset()
            self.generation = generation
        if self.confirmed:
            return False
        if self.first is None or self.last is None or now - self.last > 2:
            self.first = now
        self.last = now
        if now - self.first >= 10:
            self.confirmed = True
            return True
        return False


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



class SyncChord:
    """One receipt per continuous two-second hold, independently per keyboard."""
    def __init__(self):
        self.since = {}
        self.fired = set()

    def poll(self, keys, now, *, parent_priority=False):
        active = {fd for fd, held in keys.items() if held & CTRL and held & ALT and 31 in held}
        self.since = {fd: since for fd, since in self.since.items() if fd in active}
        self.fired.intersection_update(active)
        for fd in active:
            self.since.setdefault(fd, now)
        if parent_priority:
            self.fired.update(active)
            return False
        ready = {fd for fd in active - self.fired if now - self.since[fd] >= 2}
        self.fired.update(ready)
        return bool(ready)


class VolumeKeys:
    """Child-only media keys; bounded subprocess work never stalls supervision."""
    ACTIONS = {113: 'mute', 114: 'down', 115: 'up'}

    def __init__(self, child_uid):
        self.child_uid = child_uid
        self.pending = []
        self.process = None
        self.deadline = 0.0
        self.next_repeat = 0.0

    def event(self, code, value, now):
        if code not in self.ACTIONS or value not in {1, 2}:
            return
        if value == 2 and (code == 113 or now < self.next_repeat):
            return
        self.next_repeat = now + .15
        if len(self.pending) < 8:
            self.pending.append(self.ACTIONS[code])

    def tick(self, now, *, child_mode):
        if not child_mode:
            self.pending.clear()
        if self.process is not None:
            result = self.process.poll()
            if result is None:
                if not child_mode or now >= self.deadline:
                    try:
                        # Popen has not reaped this session leader, so its process
                        # group identity cannot be reused before the next poll.
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                return
            if result:
                print('Child volume command failed; inspect PipeWire/WirePlumber.', flush=True)
            self.process = None
        if child_mode and self.pending:
            action = self.pending.pop(0)
            environment = dict(os.environ)
            environment.pop('NOTIFY_SOCKET', None)
            try:
                self.process = subprocess.Popen(
                    ['/usr/sbin/runuser', '-u', 'toddlerbox', '--', '/usr/bin/env',
                     f'XDG_RUNTIME_DIR=/run/user/{self.child_uid}',
                     '/usr/local/libexec/toddlerbox-volume', action],
                    env=environment, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)
                self.deadline = now + 2
            except OSError:
                print('Child volume command could not start.', flush=True)


class SyncBridge:
    """Bounded asynchronous IPC; sync never waits in the controller event loop."""
    def __init__(self, health, control, child_uid):
        self.health, self.control, self.child_uid = health, control, child_uid
        self.peer = None
        self.generation = 0
        self.pending = {}
        self.starters = []

    def clear_peer(self):
        if self.peer:
            os.close(self.peer[1])
        self.peer = None

    def frame(self, credentials, address, now):
        if not credentials or credentials[1] != self.child_uid:
            return
        if not isinstance(address, bytes) or not address.startswith(b'\0toddlerbox-app-'):
            return
        pid = credentials[0]
        if not self.peer or self.peer[0] != pid or self.peer[2] != address:
            processes = launcher_processes(self.child_uid)
            pidfd = processes.pop(pid, None)
            for other in processes.values():
                os.close(other)
            if pidfd is None:
                return
            self.clear_peer()
            self.generation += 1
            self.peer = (pid, pidfd, address, now)
        else:
            self.peer = (*self.peer[:3], now)

    def healthy(self, now):
        if self.peer and now - self.peer[3] <= 5:
            try:
                return not select.select([self.peer[1]], [], [], 0)[0]
            except (OSError, ValueError):
                pass
        return False

    def receipt(self, now):
        if self.healthy(now):
            try:
                self.health.sendto(b'sync-received', self.peer[2])
            except OSError:
                pass

    def start(self, now):
        self.receipt(now)  # Also when the job is active, offline or unconfigured.
        self.starters = [p for p in self.starters if p.poll() is None]
        if self.starters:
            return
        try:
            self.starters.append(subprocess.Popen(
                ['systemctl', 'start', '--no-block', 'toddlerbox-sync.service'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        except OSError:
            pass  # Parent status/diagnostics are separate from the child receipt.

    def reply(self, address, nonce, result):
        try:
            self.control.sendto(b'save-result:' + nonce + b':' + result, address)
        except OSError:
            pass

    def request(self, message, address, now):
        nonce = message.removeprefix(b'save-current:')
        if (not re.fullmatch(b'[0-9a-f]{32}', nonce) or
                not isinstance(address, bytes) or not address.startswith(b'\0toddlerbox-sync-')):
            return
        if len(self.pending) >= 4 or not self.healthy(now):
            self.reply(address, nonce, b'unavailable')
            return
        if nonce in self.pending:
            return
        self.pending[nonce] = (address, self.peer[0], now + 5, self.generation)
        try:
            self.health.sendto(b'save-current:' + nonce, self.peer[2])
        except OSError:
            self.pending.pop(nonce)
            self.reply(address, nonce, b'unavailable')

    def result(self, message, credentials):
        match = re.fullmatch(b'save-result:([0-9a-f]{32}):(ok|failed)', message)
        if not match or not credentials or credentials[1] != self.child_uid:
            return
        nonce, result = match.groups()
        pending = self.pending.get(nonce)
        if (pending and credentials[0] == pending[1] and self.peer
                and self.peer[0] == credentials[0] and self.generation == pending[3]
                and time.monotonic() < pending[2] and self.healthy(time.monotonic())):
            self.pending.pop(nonce)
            self.reply(pending[0], nonce, result)

    def tick(self, now):
        for nonce, (address, pid, deadline, generation) in list(self.pending.items()):
            if now >= deadline:
                self.pending.pop(nonce)
                self.reply(address, nonce, b'timeout')
        self.starters = [p for p in self.starters if p.poll() is None]


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
    if (STATE / "appliance-v1").exists() and not (STATE / "setup-complete").exists():
        mode = "parent"
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
    intentional_restart = (RUNTIME / "maintenance-restart").exists()
    (RUNTIME / "maintenance-restart").unlink(missing_ok=True)
    mode, recovered = startup_mode()
    selector = selectors.DefaultSelector()
    health = bind_socket(HEALTH, 0o600, child_uid)
    control = bind_socket(CONTROL, 0o600)
    selector.register(health, selectors.EVENT_READ, "health")
    selector.register(control, selectors.EVENT_READ, "control")
    chord = EscapeChord()
    sync_chord = SyncChord()
    sync_bridge = SyncBridge(health, control, child_uid)
    volume_keys = VolumeKeys(child_uid)
    devices: dict[str, int] = {}
    watchdog = Watchdog(time.monotonic())
    observation = ObservationWindow()
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
        recover_candidate = False
        if (STATE / "appliance-v1").exists():
            from appliance import needs_candidate_recovery, invalidate_observation
            if needs_candidate_recovery(recovered, intentional_restart):
                from boot_recovery import atomic
                invalidate_observation()
                atomic(STATE / "maintenance", b"candidate controller failed\n")
                recover_candidate = True
        restart_gdm(health, child_uid)
        if recover_candidate:
            subprocess.Popen(["systemctl", "start", "--no-block", "toddlerbox-candidate-recover.service"])

    def transition(target: str, reason: str) -> None:
        if target == "child" and (STATE / "appliance-v1").exists():
            from appliance import maintenance_lock
            with maintenance_lock():
                perform_transition(target, reason)
        else:
            perform_transition(target, reason)

    def perform_transition(target: str, reason: str) -> None:
        nonlocal mode, watchdog
        if target == "child" and (STATE / "appliance-v1").exists():
            if any((STATE / name).exists() for name in ("maintenance", "recovery-error", "apt-maintenance")):
                raise ValueError("Parent maintenance/recovery must finish first")
            if not (STATE / "setup-complete").exists() and not (RUNTIME / "setup-test").exists():
                raise ValueError("Finish parent setup or use its supervised test")
            from appliance import _candidate_entry
            _candidate_entry(Path("/"))
        print(f"ToddlerBox mode={target} reason={reason}", flush=True)
        sync_bridge.clear_peer()
        if target == "parent":
            if reason.startswith("Ctrl+Alt+Home") and (RUNTIME / "setup-test").exists() and (RUNTIME / "setup-test-observed").exists():
                durable_text(RUNTIME / "setup-recovery-observed", "supervised child test returned\n")
            (RUNTIME / "setup-test").unlink(missing_ok=True)
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
        observation.reset()
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
                if _flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                    continue
                credentials = sender_credentials(ancillary)
                uid = credentials[1] if credentials else None
                if key.data == "health" and uid == child_uid and mode == "child":
                    if message == b"frame":
                        watchdog.frame(time.monotonic())
                    elif message == b"app-frame":
                        sync_bridge.frame(credentials, _address, time.monotonic())
                        # Promotion/setup evidence comes from the pinned launcher,
                        # not merely any process sharing the child account UID.
                        if ((STATE / "appliance-v1").exists() and sync_bridge.healthy(time.monotonic())
                                and sync_bridge.peer[0] == credentials[0] and sync_bridge.peer[2] == _address):
                            from appliance import observed, invalidate_observation
                            if observation.generation is not None and observation.generation != sync_bridge.generation:
                                invalidate_observation()
                            if observation.frame(time.monotonic(), generation=sync_bridge.generation):
                                observed()
                    elif message.startswith(b"save-result:"):
                        sync_bridge.result(message, credentials)
                elif key.data == "control" and uid == 0:
                    if message.startswith(b"save-current:"):
                        sync_bridge.request(message, _address, time.monotonic())
                        continue
                    reply = b"OK"
                    if message in {b"parent", b"child", b"test-child"}:
                        try:
                            if message == b"test-child":
                                (RUNTIME / "setup-test-observed").unlink(missing_ok=True)
                                (RUNTIME / "setup-recovery-observed").unlink(missing_ok=True)
                                (RUNTIME / "setup-test").touch()
                                transition("child", "parent setup test")
                            else:
                                transition(message.decode(), "parent command")
                        except (OSError, ValueError) as error:
                            reply = f"ERROR: {error}".encode()
                    elif message == b"sync":
                        sync_bridge.start(time.monotonic())
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
                            if mode == "child":
                                volume_keys.event(code, value, time.monotonic())
                        elif kind == 0 and code == 3:  # SYN_DROPPED: discard stale keys
                            chord.keys.pop(key.fd, None)
                except OSError:
                    selector.unregister(key.fd)
                    os.close(key.fd)
                    devices.pop(key.data, None)
                    chord.keys.pop(key.fd, None)
        sync_bridge.tick(time.monotonic())
        volume_keys.tick(time.monotonic(), child_mode=mode == "child")
        if mode == "child":
            if chord.held(time.monotonic()):
                transition("parent", "Ctrl+Alt+Home held for two seconds")
                continue
            parent_priority = any(keys & CTRL and keys & ALT and HOME in keys
                                  for keys in chord.keys.values())
            if sync_chord.poll(chord.keys, time.monotonic(), parent_priority=parent_priority):
                sync_bridge.start(time.monotonic())
            action = watchdog.check(time.monotonic())
            if action == "parent":
                if (STATE / "appliance-v1").exists():
                    from appliance import invalidate_observation
                    invalidate_observation()
                    from boot_recovery import latest, atomic
                    item = latest(Path("/"))
                    if item and item[1]["status"] == "pending":
                        atomic(STATE / "maintenance", b"candidate app failed\n")
                transition("parent", "watchdog restart budget exhausted")
                if (STATE / "appliance-v1").exists():
                    from boot_recovery import latest
                    item = latest(Path("/"))
                    if item and item[1]["status"] == "pending":
                        subprocess.Popen(["systemctl", "start", "--no-block", "toddlerbox-candidate-recover.service"])
            elif action == "restart":
                observation.reset()
                if (STATE / "appliance-v1").exists():
                    from appliance import invalidate_observation
                    invalidate_observation()
                print(f"Watchdog restarting GDM, attempt {watchdog.restarts}/{watchdog.max_restarts}", flush=True)
                restart_gdm(health, child_uid)
        status = {"mode": mode, "restarts": watchdog.restarts,
                  "seen_frame": watchdog.seen_frame}
        # /run is a tmpfs: diagnostic status must not generate disk writes each frame.
        (RUNTIME / "status.json").write_text(json.dumps(status) + "\n")


if __name__ == "__main__":
    main()
