"""Home always leaves an activity; unsaved work stays in the launcher and keeps saving."""
import errno
import threading
import time
from types import SimpleNamespace

import pygame
import pytest

from toddlerbox.paint.app import PaintApp
from toddlerbox.photos.app import PhotosApp
from toddlerbox.runtime import control, retained
from toddlerbox.typing.app import TypingApp


@pytest.fixture(autouse=True)
def clean_slots():
    retained._slots.clear()
    yield
    retained.flush(2.0)
    retained._slots.clear()


@pytest.fixture
def screen(tmp_path, monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    config = tmp_path / "config.yaml"
    config.write_text(f"data_root: {tmp_path / 'data'}\n")
    monkeypatch.setenv("KIDBOX_CONFIG", str(config))
    pygame.init()
    surface = pygame.display.set_mode((1024, 768))
    yield surface
    pygame.quit()


@pytest.fixture
def bounded_run(monkeypatch):
    """Stop a runaway loop after 8 s so a regression fails instead of hanging."""
    started = time.monotonic()
    monkeypatch.setattr("toddlerbox.runtime.health.stopping", lambda: time.monotonic() - started > 8)
    return started


def disk_full(*_args, **_kwargs):
    raise OSError(errno.ENOSPC, "No space left on device")


def tap_home(rect):
    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=rect.center))


def paint_something(app):
    app.canvas_surface.fill((1, 80, 120))
    app._mark_canvas_changed()


def test_paint_home_leaves_on_full_disk_and_reentry_resumes_parked_canvas(screen, monkeypatch, bounded_run):
    app = PaintApp(screen=screen)
    with monkeypatch.context() as fault:
        fault.setattr("toddlerbox.runtime.persistence.os.fsync", disk_full)
        paint_something(app)
        tap_home(app.action_buttons["home"].rect)
        app.run(quit_on_exit=False)
        assert time.monotonic() - bounded_run < 5
        assert retained.parked("paint")
        assert retained.status() != retained.DURABLE
        reopened = PaintApp(screen=screen)
        assert reopened.canvas_surface.get_at((10, 10))[:3] == (1, 80, 120)
        assert not retained.parked("paint")
    assert reopened._autosave_latest()
    assert PaintApp(screen=screen).canvas_surface.get_at((10, 10))[:3] == (1, 80, 120)


def test_parked_paint_work_becomes_durable_from_the_launcher_after_disk_recovers(screen, monkeypatch, bounded_run):
    app = PaintApp(screen=screen)
    calls = {"fail": True}
    original = retained.write_bytes
    def flaky(path, data):
        if calls["fail"]:
            disk_full()
        return original(path, data)
    monkeypatch.setattr("toddlerbox.paint.app.write_bytes", flaky)
    monkeypatch.setattr("toddlerbox.runtime.retained.write_bytes", flaky)
    paint_something(app)
    tap_home(app.action_buttons["home"].rect)
    app.run(quit_on_exit=False)
    calls["fail"] = False
    monkeypatch.setattr(retained, "RETRY_SECONDS", 0.0)
    deadline = time.monotonic() + 5
    while retained.status() != retained.DURABLE and time.monotonic() < deadline:
        time.sleep(0.02)
    assert retained.status() == retained.DURABLE
    assert PaintApp(screen=screen).canvas_surface.get_at((10, 10))[:3] == (1, 80, 120)


def test_paint_home_does_not_wait_for_a_stalled_disk(screen, monkeypatch, bounded_run):
    app = PaintApp(screen=screen)
    release = threading.Event()
    original = retained.write_bytes
    def stalled(path, data):
        assert release.wait(10)
        return original(path, data)
    monkeypatch.setattr("toddlerbox.paint.app.write_bytes", stalled)
    paint_something(app)
    tap_home(app.action_buttons["home"].rect)
    app.run(quit_on_exit=False)
    assert time.monotonic() - bounded_run < 4
    reopened = PaintApp(screen=screen)
    assert reopened._save_pending is not None
    release.set()
    reopened._finish_pending_save(wait=True)
    assert reopened._saved_revision == reopened._canvas_revision


def test_typing_home_leaves_on_full_disk_and_reentry_resumes(screen, monkeypatch, bounded_run):
    app = TypingApp(screen=screen)
    with monkeypatch.context() as fault:
        fault.setattr("toddlerbox.runtime.persistence.os.fsync", disk_full)
        for char in "kept":
            app._insert_char(char)
        tap_home(app.home_button.rect)
        app.run(quit_on_exit=False)
        assert time.monotonic() - bounded_run < 5
        assert retained.parked("typing")
        reopened = TypingApp(screen=screen)
        assert reopened.text_lines == ["kept"] and (reopened.cursor_row, reopened.cursor_col) == (0, 4)
    assert reopened._save_current()
    assert TypingApp(screen=screen).text_lines == ["kept"]


def test_typing_home_leaves_when_a_newer_save_version_blocks_writes(screen, tmp_path, bounded_run):
    typing_dir = tmp_path / "data/typing"
    typing_dir.mkdir(parents=True)
    future = b'{"version": 2, "rich_lines": []}'
    (typing_dir / "current.json").write_bytes(future)
    (typing_dir / "current-v1.json").write_bytes(future)
    app = TypingApp(screen=screen)
    app._insert_char("A")
    tap_home(app.home_button.rect)
    app.run(quit_on_exit=False)
    assert time.monotonic() - bounded_run < 5
    assert retained.status() == retained.FAILED
    assert (typing_dir / "current.json").read_bytes() == future


def fake_channel(now):
    sent = []
    return SimpleNamespace(clock=lambda: now[0], address="peer",
                           socket=SimpleNamespace(sendto=lambda data, _address: sent.append(data))), sent


def test_save_current_never_acknowledges_parked_work_until_written(monkeypatch):
    release = threading.Event()
    def slow(*_args):
        assert release.wait(5)
    monkeypatch.setattr("toddlerbox.runtime.retained.write_bytes", slow)
    retained.park(retained.ParkedWork("paint", "unused", lambda: b"x", None))
    now = [0.0]
    channel, sent = fake_channel(now)
    assert control.AppChannel._save_result(channel, b"n" * 32, None, 5.0) is False
    assert sent == []
    release.set()
    retained._slots["paint"].writer.result(2)
    assert control.AppChannel._save_result(channel, b"n" * 32, None, 5.0) is True
    assert sent == [b"save-result:" + b"n" * 32 + b":ok"]


def test_save_current_fails_while_parked_work_cannot_be_written():
    retained.park(retained.ParkedWork("typing", "unused", lambda: b"x", None, write_disabled=True))
    channel, sent = fake_channel([0.0])
    assert control.AppChannel._save_result(channel, b"m" * 32, lambda: True, 5.0) is True
    assert sent == [b"save-result:" + b"m" * 32 + b":failed"]


@pytest.mark.parametrize("make", ["paint", "typing", "photos"])
def test_escape_does_not_leave_activities_in_the_supervised_session(screen, monkeypatch, bounded_run, make):
    monkeypatch.setenv("TODDLERBOX_APP_CONTROL", "1")
    monkeypatch.delenv("TODDLERBOX_HEALTH_SOCKET", raising=False)
    app = {"paint": PaintApp, "typing": TypingApp, "photos": PhotosApp}[make](screen=screen)
    pygame.event.clear()
    for _ in range(5):
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode="\x1b"))
    frames = []
    monkeypatch.setattr("toddlerbox.runtime.health.stopping", lambda: len(frames) > 30)
    monkeypatch.setattr("toddlerbox.runtime.health.frame_complete", lambda: frames.append(1))
    app.run(quit_on_exit=False)
    assert len(frames) > 30  # Still running until the stop signal, not exited by Esc.
