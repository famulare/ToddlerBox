import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import struct
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "controller", Path(__file__).parents[1] / "system/controller.py")
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


def test_startup_failure_exhausts_three_restarts_then_parent():
    guard = controller.Watchdog(0)
    assert guard.check(89) is None
    assert [guard.check(t) for t in (90, 180, 270, 360)] == ["restart"] * 3 + ["parent"]


def test_hung_event_loop_is_detected_and_intermittent_frames_do_not_reset_budget():
    guard = controller.Watchdog(0)
    for attempt in range(3):
        now = attempt * 100 + 1
        guard.frame(now)
        assert guard.check(now + 19) is None
        assert guard.check(now + 20) == "restart"
    guard.frame(301)
    assert guard.check(321) == "parent"


def test_parent_escape_needs_continuous_hold_on_one_keyboard():
    chord = controller.EscapeChord()
    chord.event(1, 29, 1)
    chord.event(1, 56, 1)
    chord.event(2, 102, 1)
    assert not chord.held(0)
    assert not chord.held(10)
    chord.event(1, 102, 1)
    assert not chord.held(11)
    assert not chord.held(12.9)
    assert chord.held(13)
    chord.event(1, 102, 0)
    assert not chord.held(14)


def test_unplugging_keyboard_cancels_escape():
    chord = controller.EscapeChord()
    for code in [29, 56, 102]:
        chord.event(1, code, 1)
    assert not chord.held(0)
    chord.keys.pop(1)
    assert not chord.held(3)


def test_controller_restart_latches_parent_mode_across_reboot(tmp_path, monkeypatch):
    state, runtime = tmp_path / "state", tmp_path / "run"
    state.mkdir()
    runtime.mkdir()
    monkeypatch.setattr(controller, "STATE", state)
    monkeypatch.setattr(controller, "RUNTIME", runtime)
    assert controller.startup_mode() == ("child", False)
    assert controller.startup_mode() == ("parent", True)
    assert (state / "parent-mode").read_text() == "controller restarted\n"
    assert "AutomaticLoginEnable=false" in (runtime / "gdm.conf").read_text()
    (runtime / "controller-started").unlink()
    assert controller.startup_mode() == ("parent", False)


def test_restart_reconciles_running_gdm_after_readiness(tmp_path, monkeypatch):
    events = []
    state, runtime = tmp_path / "state", tmp_path / "run"
    state.mkdir()
    runtime.mkdir()
    (runtime / "controller-started").touch()
    monkeypatch.setattr(controller, "STATE", state)
    monkeypatch.setattr(controller, "RUNTIME", runtime)
    monkeypatch.setattr(controller.pwd, "getpwnam", lambda _: type("User", (), {"pw_uid": 123})())
    monkeypatch.setenv("NOTIFY_SOCKET", "@notify-test")

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def sendto(self, message, address):
            events.append((message, address))

    monkeypatch.setattr(controller, "bind_socket", lambda *args: FakeSocket())
    monkeypatch.setattr(controller.socket, "socket", lambda *args: FakeSocket())
    monkeypatch.setattr(controller.selectors, "DefaultSelector", lambda: type(
        "Selector", (), {"register": lambda *args: None})())

    class Reconciled(Exception):
        pass

    def restart(health, uid):
        assert uid == 123
        assert (runtime / "mode").read_text() == "parent\n"
        assert (state / "parent-mode").exists()
        events.append("restart")
        raise Reconciled

    monkeypatch.setattr(controller, "restart_gdm", restart)
    with pytest.raises(Reconciled):
        controller.main()
    assert events == [(b"READY=1", "\0notify-test"), "restart"]


def test_restart_still_selects_parent_when_latch_disk_is_full(tmp_path, monkeypatch):
    state, runtime = tmp_path / "state", tmp_path / "run"
    state.mkdir()
    runtime.mkdir()
    (runtime / "controller-started").touch()
    monkeypatch.setattr(controller, "STATE", state)
    monkeypatch.setattr(controller, "RUNTIME", runtime)
    write = controller.durable_text

    def disk_full(path, text):
        if path.parent == state:
            raise OSError("No space left on device")
        write(path, text)

    monkeypatch.setattr(controller, "durable_text", disk_full)
    assert controller.startup_mode() == ("parent", True)
    assert (runtime / "mode").read_text() == "parent\n"


def test_event_batch_tolerates_health_already_drained_by_shutdown(tmp_path, monkeypatch):
    runtime = tmp_path / "run"
    monkeypatch.setattr(controller, "RUNTIME", runtime)
    monkeypatch.setattr(controller, "STATE", tmp_path / "state")
    monkeypatch.setattr(controller, "startup_mode", lambda: ("parent", False))
    monkeypatch.setattr(controller.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=123))
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.setattr(controller.glob, "glob", lambda _: [])

    class Health:
        def recvmsg(self, *args):
            raise BlockingIOError

    health = Health()

    class FinishedBatch(Exception):
        pass

    class Selector:
        selected = False

        def register(self, *args):
            pass

        def select(self, _):
            if self.selected:
                raise FinishedBatch
            self.selected = True
            return [(SimpleNamespace(data="health", fileobj=health), 1)]

    monkeypatch.setattr(controller, "bind_socket", lambda *args: health)
    monkeypatch.setattr(controller.selectors, "DefaultSelector", Selector)
    with pytest.raises(FinishedBatch):
        controller.main()
    assert json.loads((runtime / "status.json").read_text())["mode"] == "parent"


@pytest.fixture
def shutdown_environment(monkeypatch):
    # Credential delivery/pidfd readiness are kernel boundaries. Keep these unit
    # tests portable to sandboxes that prohibit SO_PASSCRED and process signalling.
    packets, readiness, signals, closed = [], [], [], []
    now = [0.0]

    class Health:
        def recvmsg(self, *args):
            return packets.pop(0)

    health = Health()

    class Selector:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def register(self, *args):
            pass

        def unregister(self, fd):
            pass

        def select(self, timeout):
            now[0] += 0.01 if readiness else timeout
            return readiness.pop(0) if readiness else []

    def packet(pid=123, uid=1000, message=b"shutdown-complete"):
        packets.append((message, [(socket.SOL_SOCKET, socket.SCM_CREDENTIALS,
                                   struct.pack("3i", pid, uid, 1000))], 0, None))
        readiness.append([(SimpleNamespace(data=None, fd=9), 1)])

    monkeypatch.setattr(controller, "launcher_processes", lambda _: {123: 42})
    monkeypatch.setattr(controller.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(controller.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(controller.signal, "pidfd_send_signal", lambda fd, sig: signals.append((fd, sig)))
    monkeypatch.setattr(controller.os, "close", closed.append)
    return SimpleNamespace(health=health, packet=packet, readiness=readiness,
                           signals=signals, closed=closed, now=now)


def test_shutdown_waits_for_authenticated_completion(shutdown_environment):
    env = shutdown_environment
    env.packet()
    controller.stop_launchers(env.health, 1000, grace=5)
    assert env.signals == [(42, signal.SIGTERM)]
    assert env.closed == [42]
    assert env.now[0] < 5


def test_frozen_launcher_cannot_extend_shutdown_grace(shutdown_environment):
    env = shutdown_environment
    controller.stop_launchers(env.health, 1000, grace=5)
    assert env.signals == [(42, signal.SIGTERM), (42, signal.SIGKILL)]
    assert env.now[0] == 5
    assert env.closed == [42]


@pytest.mark.parametrize("pid,uid,message", [
    (124, 1000, b"shutdown-complete"),
    (123, 1001, b"shutdown-complete"),
    (123, 1000, b"frame"),
])
def test_unrelated_acknowledgement_cannot_finish_shutdown(shutdown_environment, pid, uid, message):
    env = shutdown_environment
    env.packet(pid, uid, message)
    controller.stop_launchers(env.health, 1000, grace=5)
    assert env.signals == [(42, signal.SIGTERM), (42, signal.SIGKILL)]
    assert env.now[0] == 5


def test_natural_exit_finishes_shutdown_without_ack(shutdown_environment):
    env = shutdown_environment
    env.readiness.append([(SimpleNamespace(data=123, fd=42), 1)])
    controller.stop_launchers(env.health, 1000, grace=5)
    assert env.signals == [(42, signal.SIGTERM)]
    assert env.now[0] < 5


def test_shutdown_tolerates_stale_socket_readiness(shutdown_environment, monkeypatch):
    env = shutdown_environment

    def drained(*args):
        raise BlockingIOError

    monkeypatch.setattr(env.health, "recvmsg", drained)
    env.readiness.append([(SimpleNamespace(data=None, fd=9), 1)])
    controller.stop_launchers(env.health, 1000, grace=5)
    assert env.signals == [(42, signal.SIGTERM), (42, signal.SIGKILL)]
    assert env.now[0] == 5


def test_exiting_process_is_not_signalled_by_reused_numeric_pid(shutdown_environment, monkeypatch):
    env = shutdown_environment

    def exited(fd, sig):
        assert fd == 42
        raise ProcessLookupError

    monkeypatch.setattr(controller.signal, "pidfd_send_signal", exited)
    controller.stop_launchers(env.health, 1000, grace=5)
    assert env.closed == [42]
    assert env.now[0] == 0


def test_launcher_identity_accepts_absolute_python_path_and_closes_other_pidfds(tmp_path, monkeypatch):
    for pid, args in [(10, b"/opt/release/.venv/bin/python\0-m\0toddlerbox.launcher\0"),
                      (11, b"python\0-m\0unrelated.launcher\0")]:
        directory = tmp_path / str(pid)
        directory.mkdir()
        (directory / "cmdline").write_bytes(args)
    monkeypatch.setattr(controller, "Path", lambda _: tmp_path)
    opened, closed = [], []
    monkeypatch.setattr(controller.os, "pidfd_open", lambda pid: opened.append(pid) or pid + 100)
    monkeypatch.setattr(controller.os, "close", closed.append)
    assert controller.launcher_processes(os.getuid()) == {10: 110}
    assert set(opened) == {10, 11}
    assert closed == [111]


def test_gdm_restart_does_not_inherit_notify_socket(monkeypatch):
    calls = []
    monkeypatch.setenv("NOTIFY_SOCKET", "@controller-notify")
    monkeypatch.setattr(controller, "stop_launchers", lambda *args: calls.append("stopped"))
    monkeypatch.setattr(controller.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    controller.restart_gdm(None, 123)
    assert calls[0] == "stopped"
    assert calls[1][0][0] == ["systemctl", "restart", "--no-block", "gdm3.service"]
    assert "NOTIFY_SOCKET" not in calls[1][1]["env"]
    assert calls[1][1]["timeout"] == 2


@pytest.fixture
def releases(tmp_path):
    root = tmp_path / "app"
    for name in ["old", "new"]:
        (root / "releases" / name).mkdir(parents=True)
    (root / "current").symlink_to(root / "releases/new")
    (root / "previous").symlink_to(root / "releases/old")
    return root


def test_rollback_persists_one_switch_and_retains_fallback(releases, monkeypatch):
    synced = []
    monkeypatch.setattr(controller, "sync_directory", synced.append)
    controller.rollback(releases)
    assert (releases / "current").resolve() == releases / "releases/old"
    assert (releases / "previous").resolve() == releases / "releases/old"
    assert synced == [releases]
    with pytest.raises(ValueError, match="already current"):
        controller.rollback(releases)


def test_rollback_directory_sync_failure_retains_identifiable_fallback(releases, monkeypatch):
    def fail(_):
        raise OSError("fsync failed")

    monkeypatch.setattr(controller, "sync_directory", fail)
    with pytest.raises(OSError, match="fsync failed"):
        controller.rollback(releases)
    # Replacement is visible but its durability is uncertain; do not undo it.
    assert (releases / "current").resolve() == (releases / "previous").resolve()
    assert (releases / "releases/new").is_dir()


def test_rollback_refuses_different_declared_schemas(releases):
    (releases / "releases/new/data-schema.json").write_text(json.dumps({"version": 1, "paint": 1, "typing": 2}))
    with pytest.raises(ValueError, match="schemas differ"):
        controller.rollback(releases)
    assert (releases / "current").resolve() == releases / "releases/new"


def test_release_switch_lock_refuses_concurrent_mutation(releases):
    with controller.release_lock(releases):
        with pytest.raises(BlockingIOError):
            controller.rollback(releases)
    assert (releases / "current").resolve() == releases / "releases/new"


def test_rollback_refuses_release_link_outside_managed_tree(releases, tmp_path):
    (releases / "previous").unlink()
    (releases / "previous").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="outside releases"):
        controller.rollback(releases)
