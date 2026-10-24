"""Regressions for the independent review of the hardening branch (Codex, 2026-10-23)."""
import errno
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace

import pygame
import pytest

from toddlerbox.paint.app import PaintApp
from toddlerbox.runtime import control, persistence, retained
from toddlerbox.typing.app import TypingApp, _load_recent_sessions


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


def drain(app, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app._service_transition()
        if app._transition_request is None and app._transition_pending is None:
            return
        time.sleep(0.005)
    raise AssertionError("transition did not finish")


def fsync_dir_fails(*_args):
    raise OSError(errno.EIO, "directory fsync failed")


def draw(app):
    x, y = app.canvas_rect.center
    app._handle_pointer_down((x, y))
    app._handle_pointer_move((x + 40, y + 25))
    app._handle_pointer_up()


def test_uncertain_paint_archive_is_never_treated_as_preserving_current_work(screen, monkeypatch):
    app = PaintApp(screen=screen)
    draw(app)
    before = pygame.image.tobytes(app.canvas_surface, "RGB")
    monkeypatch.setattr(persistence, "sync_directory", fsync_dir_fails)
    for _ in range(2):
        app._begin_transition("new")
        drain(app)
        assert pygame.image.tobytes(app.canvas_surface, "RGB") == before


def test_uncertain_typing_archive_is_never_treated_as_preserving_current_work(screen, monkeypatch):
    app = TypingApp(screen=screen)
    for char in "keep":
        app._insert_char(char)
    monkeypatch.setattr(persistence, "sync_directory", fsync_dir_fails)
    for _ in range(2):
        app._begin_transition("new")
        drain(app)
        assert app.text_lines == ["keep"]


def tap_home(rect):
    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))


def test_pending_save_request_follows_work_into_and_out_of_the_launcher(screen, monkeypatch):
    release = threading.Event()
    original = persistence.write_bytes
    def stalled(path, data):
        assert release.wait(10)
        return original(path, data)
    monkeypatch.setattr("toddlerbox.paint.app.write_bytes", stalled)
    monkeypatch.setattr("toddlerbox.runtime.health.stopping", lambda: False)
    app = PaintApp(screen=screen)
    app.canvas_surface.fill((5, 6, 7))
    app._mark_canvas_changed()
    sent = []
    now = [0.0]
    channel = SimpleNamespace(clock=lambda: now[0], address="peer", serviced=[], received_at=0,
                              socket=SimpleNamespace(sendto=lambda data, _a: sent.append(data),
                                                     recvmsg=lambda *a: (_ for _ in ()).throw(BlockingIOError())))
    channel._save_result = lambda *a: control.AppChannel._save_result(channel, *a)
    nonce = b"a" * 32
    channel.pending_saves = {nonce: (app._save_for_control, 5.0)}
    control.AppChannel.service(channel, app._save_for_control)
    tap_home(app.action_buttons["home"].rect)
    app.run(quit_on_exit=False)
    control.AppChannel.service(channel, None)  # Home: parked, still unwritten.
    reopened = PaintApp(screen=screen)
    control.AppChannel.service(channel, reopened._save_for_control)
    assert sent == [] and not (app.paint_dir / "latest.png").exists()
    release.set()
    reopened._finish_pending_save(wait=True)
    control.AppChannel.service(channel, reopened._save_for_control)
    assert sent == [b"save-result:" + nonce + b":ok"]
    assert (app.paint_dir / "latest.png").exists()


@pytest.mark.parametrize("make", ["paint", "typing"])
def test_home_is_not_held_behind_a_stalled_new(screen, monkeypatch, make):
    release = threading.Event()
    module = "toddlerbox.paint.app" if make == "paint" else "toddlerbox.typing.app"
    original = persistence.publish_new_bytes
    def stalled(*args):
        assert release.wait(10)
        return original(*args)
    monkeypatch.setattr(module + ".publish_new_bytes", stalled)
    started = time.monotonic()
    monkeypatch.setattr("toddlerbox.runtime.health.stopping", lambda: time.monotonic() - started > 8)
    if make == "paint":
        app = PaintApp(screen=screen)
        draw(app)
        expected = pygame.image.tobytes(app.canvas_surface, "RGB")
        home = app.action_buttons["home"].rect
    else:
        app = TypingApp(screen=screen)
        app._insert_char("Z")
        home = app.home_button.rect
    app._begin_transition("new")
    app._service_transition()
    tap_home(home)
    app.run(quit_on_exit=False)
    assert time.monotonic() - started < 5
    reopened = (PaintApp if make == "paint" else TypingApp)(screen=screen)
    if make == "paint":
        assert pygame.image.tobytes(reopened.canvas_surface, "RGB") == expected
    else:
        assert reopened.text_lines == ["Z"]
    release.set()


def test_term_with_a_stalled_disk_lets_the_activity_finish_promptly(screen, monkeypatch):
    release = threading.Event()
    original = persistence.write_bytes
    def stalled(path, data):
        release.wait(10)
        return original(path, data)
    monkeypatch.setattr("toddlerbox.typing.app.write_bytes", stalled)
    app = TypingApp(screen=screen)
    app._insert_char("T")
    app._request_autosave()
    monkeypatch.setattr("toddlerbox.runtime.health.stopping", lambda: True)
    started = time.monotonic()
    app.run(quit_on_exit=False)
    assert time.monotonic() - started < 2.5
    assert retained.parked("typing")
    release.set()


def test_a_stalled_background_write_cannot_hold_the_process_open(tmp_path):
    script = textwrap.dedent("""
        import time
        from toddlerbox.runtime.workers import DaemonExecutor
        DaemonExecutor("stalled").submit(time.sleep, 60)
        print("exiting", flush=True)
    """)
    started = time.monotonic()
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.stdout.strip() == "exiting" and time.monotonic() - started < 10


def test_interrupted_archive_publication_leaves_single_link_files(screen, tmp_path):
    paint = tmp_path / "data/paint"
    paint.mkdir(parents=True)
    archive = paint / "2026-10-23_120000.png"
    pygame.image.save(pygame.Surface((8, 8)), str(archive))
    os.link(archive, paint / ".2026-10-23_120000.tmp.png")  # Crash between link and unlink.
    app = PaintApp(screen=screen)
    assert [p.name for p in app._recall_archives()] == [archive.name]
    assert archive.stat().st_nlink == 1
    assert not list(paint.glob(".*"))


def test_quarantine_never_leaves_two_names_for_one_file(screen, tmp_path):
    paint = tmp_path / "data/paint"
    paint.mkdir(parents=True)
    (paint / "latest.png").write_bytes(b"damaged")
    PaintApp(screen=screen)
    (corrupt,) = paint.glob("corrupt-*.png")
    assert corrupt.stat().st_nlink == 1 and not (paint / "latest.png").exists()


def test_malformed_style_is_salvaged_and_zero_width_previews_render(screen, tmp_path):
    typing_dir = tmp_path / "data/typing"
    (typing_dir / "archive").mkdir(parents=True)
    (typing_dir / "current.json").write_text(json.dumps({
        "version": 1, "cursor": [0, 0], "size": 25, "style": "plain",
        "rich_lines": [[{"char": "o", "size": 25, "style": {}}, {"char": "k", "size": 25, "style": "plain"}]]}))
    (typing_dir / "archive/1.json").write_text(json.dumps({
        "version": 1, "timestamp": "t", "rich_lines": [[{"char": "͏", "size": 25, "style": "plain"}]]}))
    app = TypingApp(screen=screen)
    assert app.text_lines == ["k"]
    assert len(_load_recent_sessions(app.sessions_path)) == 1
    app._open_recall()
    app._render()
