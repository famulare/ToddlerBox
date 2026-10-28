"""Repeated New/Recall taps never fill the nondestructive archive capacity."""
import time

import pygame
import pytest

from toddlerbox.paint.app import PaintApp
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


def drain(app, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app._service_transition()
        if app._transition_request is None and app._transition_pending is None:
            app._finish_pending_save(wait=True)
            return
        time.sleep(0.005)
    raise AssertionError("transition did not finish")


def tap(app, kind, item=None):
    app._begin_transition(kind, item)
    drain(app)


def draw(app, offset=0):
    x, y = app.canvas_rect.center
    app._handle_pointer_down((x + offset, y))
    app._handle_pointer_move((x + offset + 40, y + 25))
    app._handle_pointer_up()


def paint_archives(app):
    return app._recall_archives()


def typing_archives(app):
    return [s for s in _load_recent_sessions(app.sessions_path)]


def test_mashing_new_on_blank_canvas_creates_no_archives(screen):
    app = PaintApp(screen=screen)
    for _ in range(105):
        tap(app, "new")
    assert paint_archives(app) == []


def test_mashing_new_after_drawing_archives_the_drawing_once(screen):
    app = PaintApp(screen=screen)
    draw(app)
    for _ in range(20):
        tap(app, "new")
    assert len(paint_archives(app)) == 1


def test_unchanged_recalled_painting_is_not_archived_again(screen):
    app = PaintApp(screen=screen)
    draw(app)
    tap(app, "new")
    draw(app, offset=-120)
    tap(app, "new")
    first, second = sorted(paint_archives(app), key=lambda p: p.name)
    for _ in range(10):
        tap(app, "recall", first)
        tap(app, "recall", second)
    assert len(paint_archives(app)) == 2


def test_blank_new_and_recall_still_work_at_capacity(screen):
    app = PaintApp(screen=screen)
    app.config["paint"]["max_archives"] = 1
    draw(app)
    tap(app, "new")
    (archive,) = paint_archives(app)
    tap(app, "new")  # Blank canvas at capacity: nothing to preserve, no refusal.
    tap(app, "recall", archive)
    assert not app.recall_open
    assert pygame.image.tobytes(app.canvas_surface, "RGB") != b"\xff" * len(pygame.image.tobytes(app.canvas_surface, "RGB"))
    tap(app, "new")  # Unchanged recall at capacity is already preserved.
    assert paint_archives(app) == [archive]


def test_restored_copy_of_newest_archive_is_not_duplicated_next_session(screen):
    app = PaintApp(screen=screen)
    draw(app)
    tap(app, "new")
    (archive,) = paint_archives(app)
    tap(app, "recall", archive)
    app._autosave_latest()
    reopened = PaintApp(screen=screen)
    tap(reopened, "new")
    assert paint_archives(reopened) == [archive]


def test_changed_drawing_is_still_archived_after_recall(screen):
    app = PaintApp(screen=screen)
    draw(app)
    tap(app, "new")
    (archive,) = paint_archives(app)
    tap(app, "recall", archive)
    draw(app, offset=-150)
    tap(app, "new")
    assert len(paint_archives(app)) == 2


def test_mashing_typing_new_on_empty_document_creates_no_archives(screen):
    app = TypingApp(screen=screen)
    for _ in range(205):
        tap(app, "new")
    assert typing_archives(app) == []
    app._insert_char("\n")
    tap(app, "new")
    assert typing_archives(app) == []


def test_typing_new_and_recall_mashing_archives_each_document_once(screen):
    app = TypingApp(screen=screen)
    for char in "cat":
        app._insert_char(char)
    for _ in range(10):
        tap(app, "new")
    (saved,) = typing_archives(app)
    for _ in range(10):
        tap(app, "recall", saved)
    assert [s.preview for s in typing_archives(app)] == ["cat"]
    app._insert_char("s")
    tap(app, "new")
    assert sorted(s.preview for s in typing_archives(app)) == ["cat", "cats"]


def test_typing_blank_new_still_works_at_capacity(screen):
    app = TypingApp(screen=screen)
    app.config["typing"] = {"max_archives": 1}
    app._insert_char("A")
    tap(app, "new")
    assert app.text_lines == [""]
    tap(app, "new")
    (saved,) = typing_archives(app)
    tap(app, "recall", saved)
    assert app.text_lines == ["A"]
    tap(app, "new")
    assert app.text_lines == [""]
    assert len(typing_archives(app)) == 1
