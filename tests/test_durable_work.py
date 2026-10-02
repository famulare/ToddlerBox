import errno
import json
from pathlib import Path

import pygame
import pytest

from toddlerbox.paint.app import PaintApp
from toddlerbox.runtime import persistence
from toddlerbox.typing.app import TypingApp, _load_recent_sessions


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


def disk_full(*args, **kwargs):
    raise OSError(errno.ENOSPC, "No space left on device")


def test_failed_write_preserves_previous_complete_file(tmp_path):
    path = tmp_path / "current.json"
    path.write_bytes(b"previous work")
    def interrupted(temporary):
        temporary.write_bytes(b"partial replacement")
        disk_full()
    with pytest.raises(OSError):
        persistence.atomic_write(path, interrupted)
    assert path.read_bytes() == b"previous work"
    assert list(tmp_path.iterdir()) == [path]


def test_failed_flush_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "latest.png"
    path.write_bytes(b"previous work")
    monkeypatch.setattr(persistence.os, "fsync", disk_full)
    with pytest.raises(OSError):
        persistence.write_bytes(path, b"new work")
    assert path.read_bytes() == b"previous work"


def test_failed_directory_sync_reports_visible_but_unconfirmed_commit(tmp_path, monkeypatch):
    path = tmp_path / "current.json"
    path.write_bytes(b"previous work")
    monkeypatch.setattr(persistence, "sync_directory", disk_full)
    with pytest.raises(persistence.CommitUncertainError, match="Replacement visible"):
        persistence.write_bytes(path, b"next work")
    assert path.read_bytes() == b"next work"
    assert list(tmp_path.iterdir()) == [path]


def test_typing_restores_current_work_and_style_after_exit(screen):
    app = TypingApp(screen=screen)
    app._set_text_font(size=50, style="bold")
    for character in "Hello\nworld":
        app._insert_char(character)
    pygame.event.post(pygame.event.Event(pygame.QUIT))
    app.run(quit_on_exit=False)
    reopened = TypingApp(screen=screen)
    assert reopened.text_lines == ["Hello", "world"]
    assert reopened.rich_lines[0][0].style == "bold"
    assert reopened.current_text_size == 50
    assert (reopened.cursor_row, reopened.cursor_col) == (1, 5)


def test_typing_periodic_save_precedes_forced_interruption(screen):
    app = TypingApp(screen=screen)
    app._insert_char("A")
    app.last_autosave = 0
    def interrupt_after_frame():
        assert app.current_path.exists()
        raise RuntimeError("simulated interruption")
    # Render once at startup, then stop after a completed event-loop iteration.
    original = app._render
    count = 0
    def render():
        nonlocal count
        count += 1
        if count > 1:
            interrupt_after_frame()
        original()
    app._render = render
    with pytest.raises(RuntimeError):
        app._run()
    assert TypingApp(screen=screen).text_lines == ["A"]


def test_typing_new_keeps_work_if_archive_cannot_be_saved(screen, monkeypatch):
    app = TypingApp(screen=screen)
    app._insert_char("A")
    monkeypatch.setattr("toddlerbox.typing.app.write_bytes", disk_full)
    assert not app._archive_session()
    assert app.text_lines == ["A"]
    assert not app._save_current()
    assert app.text_lines == ["A"]


def test_new_typing_archives_recall_without_legacy_jsonl(screen):
    app = TypingApp(screen=screen)
    app._insert_char("A")
    assert app._archive_session()
    assert not app.sessions_path.exists()
    assert _load_recent_sessions(app.sessions_path)[0].preview == "A"


def test_corrupt_typing_current_is_preserved(screen):
    app = TypingApp(screen=screen)
    app.current_path.write_text("{broken")
    reopened = TypingApp(screen=screen)
    assert reopened.text_lines == [""]
    assert next(app.typing_dir.glob("corrupt-*.json")).read_text() == "{broken"
    assert reopened._save_current()


def test_paint_restores_canvas_after_return_home(screen):
    app = PaintApp(screen=screen)
    app.canvas_surface.fill((1, 80, 120))
    pygame.event.post(pygame.event.Event(pygame.QUIT))
    app.run(quit_on_exit=False)
    restored = PaintApp(screen=screen)
    assert restored.canvas_surface.get_at((10, 10))[:3] == (1, 80, 120)
    assert (app.paint_dir / "latest.png").exists()


def test_paint_new_and_home_preserve_work_when_disk_full(screen, monkeypatch):
    app = PaintApp(screen=screen)
    app.canvas_surface.fill((1, 80, 120))
    monkeypatch.setattr("toddlerbox.paint.app._save_surface_atomic", disk_full)
    assert not app._handle_pointer_down(app.action_buttons["new"].rect.center)
    assert app.canvas_surface.get_at((10, 10))[:3] == (1, 80, 120)
    assert not app._handle_pointer_down(app.action_buttons["home"].rect.center)


def test_corrupt_paint_current_is_preserved(screen):
    app = PaintApp(screen=screen)
    (app.paint_dir / "latest.png").write_bytes(b"broken")
    PaintApp(screen=screen)
    assert next(app.paint_dir.glob("corrupt-*.png")).read_bytes() == b"broken"
