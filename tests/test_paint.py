import os
from pathlib import Path
from types import SimpleNamespace

import pygame

from toddlerbox.paint.app import _coerce_archive_limit
from toddlerbox.paint.app import _fountain_width_for_direction
from toddlerbox.paint.app import _load_canvas_image
from toddlerbox.paint.app import _list_archives
from toddlerbox.paint.app import _rollover_latest_snapshot
from toddlerbox.paint.app import _save_surface_atomic
from toddlerbox.paint.app import PaintApp
from toddlerbox.ui.common import Button
from toddlerbox.ui.common import is_primary_pointer_event


def test_list_archives_includes_latest(tmp_path):
    (tmp_path / "latest.png").write_bytes(b"")
    (tmp_path / "2024-01-01_120000.png").write_bytes(b"")
    (tmp_path / "2024-01-02_120000.png").write_bytes(b"")

    os.utime(tmp_path / "2024-01-01_120000.png", (1, 1))
    os.utime(tmp_path / "2024-01-02_120000.png", (2, 2))
    os.utime(tmp_path / "latest.png", (3, 3))

    archives = _list_archives(tmp_path)
    names = [p.name for p in archives]
    assert "latest.png" in names
    assert names[0] == "latest.png"


def test_list_archives_orders_by_mtime(tmp_path):
    a = tmp_path / "2024-01-01_120000.png"
    b = tmp_path / "2024-01-02_120000.png"
    c = tmp_path / "2024-01-03_120000.png"

    for path in (a, b, c):
        path.write_bytes(b"")

    os.utime(a, (10, 10))
    os.utime(c, (20, 20))
    os.utime(b, (30, 30))

    archives = _list_archives(tmp_path)
    assert [p.name for p in archives[:3]] == [b.name, c.name, a.name]


def test_coerce_archive_limit_clamps_and_falls_back():
    assert _coerce_archive_limit("5", 100) == 5
    assert _coerce_archive_limit(-2, 100) == 1
    assert _coerce_archive_limit("bad", 100) == 100

def test_rollover_latest_snapshot_archives_existing_latest(tmp_path):
    latest = tmp_path / "latest.png"
    latest.write_bytes(b"session")

    archived = _rollover_latest_snapshot(tmp_path)

    assert archived is not None
    assert archived.exists()
    assert archived.read_bytes() == b"session"
    assert not latest.exists()


def test_rollover_latest_snapshot_adds_counter_on_collision(tmp_path):
    latest = tmp_path / "latest.png"
    latest.write_bytes(b"new")
    existing = tmp_path / "2026-02-06_101112.png"
    existing.write_bytes(b"old")

    class FixedNow:
        def strftime(self, _fmt: str) -> str:
            return "2026-02-06_101112"

    archived = _rollover_latest_snapshot(tmp_path, now=FixedNow())

    assert archived == tmp_path / "2026-02-06_101112_1.png"
    assert archived.exists()
    assert archived.read_bytes() == b"new"
    assert existing.read_bytes() == b"old"


def test_primary_pointer_event_accepts_left_mouse_button():
    event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(10, 10))
    assert is_primary_pointer_event(event, is_down=True)


def test_primary_pointer_event_accepts_touch_emulated_mouse_button_zero():
    event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=0, pos=(10, 10), touch=True)
    assert is_primary_pointer_event(event, is_down=True)


def test_primary_pointer_event_rejects_right_mouse_button():
    event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(10, 10))
    assert not is_primary_pointer_event(event, is_down=True)


def test_fountain_width_changes_with_direction():
    size = 10
    horizontal = _fountain_width_for_direction(size, (0, 0), (20, 0), nib_angle_degrees=0)
    vertical = _fountain_width_for_direction(size, (0, 0), (0, 20), nib_angle_degrees=0)
    assert vertical > horizontal
    assert vertical - horizontal >= 12


def test_fountain_width_respects_ratio_bounds():
    size = 12
    min_ratio = 0.4
    max_ratio = 1.3
    width = _fountain_width_for_direction(
        size,
        (5, 5),
        (5, 5),
        min_ratio=min_ratio,
        max_ratio=max_ratio,
    )
    assert int(round(size * min_ratio)) <= width <= int(round(size * max_ratio))


def test_load_canvas_image_returns_none_on_image_error(monkeypatch, tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not-an-image")

    def _raise(*_args, **_kwargs):
        raise pygame.error("bad image")

    monkeypatch.setattr(pygame.image, "load", _raise)
    assert _load_canvas_image(path, (64, 64)) is None


def test_save_surface_atomic_cleans_tmp_file_on_failure(monkeypatch, tmp_path):
    surface = pygame.Surface((4, 4))
    path = tmp_path / "latest.png"
    tmp_pathname = tmp_path / ".latest.tmp.png"
    tmp_pathname.write_bytes(b"stale")

    def _raise(*_args, **_kwargs):
        raise pygame.error("save failed")

    monkeypatch.setattr(pygame.image, "save", _raise)
    try:
        _save_surface_atomic(surface, path)
    except pygame.error:
        pass

    assert not tmp_pathname.exists()


def _make_pointer_resolution_app() -> PaintApp:
    app = PaintApp.__new__(PaintApp)
    app.screen_rect = pygame.Rect(0, 0, 1920, 1080)
    app.recall_open = False
    app.current_stroke = None
    app.recall_items = []
    app.recall_strip_rect = pygame.Rect(0, 0, 0, 0)
    app.action_buttons = {
        "home": Button(rect=pygame.Rect(1800, 20, 80, 80)),
        "new": Button(rect=pygame.Rect(20, 900, 220, 60)),
        "undo": Button(rect=pygame.Rect(20, 970, 105, 60)),
        "redo": Button(rect=pygame.Rect(135, 970, 105, 60)),
        "recall": Button(rect=pygame.Rect(20, 720, 220, 160)),
    }
    app.tool_buttons = {"round": Button(rect=pygame.Rect(20, 20, 100, 100))}
    app.size_buttons = {6: Button(rect=pygame.Rect(20, 240, 100, 60))}
    app.palette_buttons = [Button(rect=pygame.Rect(20, 320, 100, 40))]
    app.canvas_rect = pygame.Rect(260, 20, 1640, 1040)
    return app


def test_event_pos_prefers_raw_mouse_position_for_home_button(monkeypatch):
    app = _make_pointer_resolution_app()
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (1280, 720))
    event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(1840, 60), button=1)
    assert app._event_pos(event) == (1840, 60)


def test_event_pos_prefers_scaled_mouse_position_for_canvas(monkeypatch):
    app = _make_pointer_resolution_app()
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (1280, 720))
    event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(640, 360), button=1)
    assert app._event_pos(event) == (960, 540)


def test_event_pos_keeps_touch_emulated_mouse_unscaled(monkeypatch):
    app = _make_pointer_resolution_app()
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (1280, 720))
    event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(640, 360), button=1, touch=True)
    assert app._event_pos(event) == (640, 360)


def test_event_pos_keeps_finger_event_unscaled(monkeypatch):
    app = _make_pointer_resolution_app()
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (1280, 720))
    finger_down = getattr(pygame, "FINGERDOWN", None)
    if finger_down is None:
        return
    event = pygame.event.Event(finger_down, x=0.5, y=0.5, finger_id=1)
    assert app._event_pos(event) == (960, 540)


def test_handle_pointer_down_home_returns_true(monkeypatch):
    app = _make_pointer_resolution_app()
    monkeypatch.setattr(app, "_autosave_latest", lambda: True)
    assert app._handle_pointer_down((1840, 60)) is True


def test_handle_pointer_down_new_archives_and_resets(monkeypatch):
    app = _make_pointer_resolution_app()
    calls: list[str] = []

    monkeypatch.setattr(app, "_archive_current", lambda: calls.append("archive") or True)
    monkeypatch.setattr(app, "_reset_canvas", lambda: calls.append("reset"))
    monkeypatch.setattr(app, "_autosave_latest", lambda: True)

    assert app._handle_pointer_down((40, 920)) is False
    assert calls == ["archive", "reset"]


def test_handle_pointer_down_scaled_canvas_starts_stroke(monkeypatch):
    app = _make_pointer_resolution_app()
    app.current_tool = "round"
    app.current_size = 6
    app.current_color = (1, 2, 3)
    app.undo_stack = []
    app.redo_stack = []
    app.canvas_surface = pygame.Surface(app.canvas_rect.size)

    monkeypatch.setattr(app, "_push_undo", lambda: None)

    resolved = app._resolve_pointer_pos((640, 360), (960, 540))
    assert resolved == (960, 540)
    assert app._handle_pointer_down(resolved) is False
    assert app.current_stroke is not None
    assert app.current_stroke.points == [(700, 520)]


def test_should_reset_for_key_ignores_escape():
    app = _make_pointer_resolution_app()
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0)
    assert app._should_reset_for_key(event) is False


def test_should_reset_for_key_matches_function_shortcut():
    app = _make_pointer_resolution_app()
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11, mod=0)
    assert app._should_reset_for_key(event) is True


def test_should_reset_for_key_matches_modified_chord():
    app = _make_pointer_resolution_app()
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_ALT)
    assert app._should_reset_for_key(event) is True


def test_handle_resume_resets_pointer_state_and_clears_motion(monkeypatch):
    app = _make_pointer_resolution_app()
    app.logger = SimpleNamespace(info=lambda *_args, **_kwargs: None)
    app.pointer_down = True
    app.current_stroke = object()
    app.recall_strip_drag_last_y = 50
    app.recall_pressed_index = 2
    app.recall_drag_distance = 17
    app.last_autosave = 0.0

    cleared: list[int] = []

    monkeypatch.setattr("toddlerbox.paint.app.time.monotonic", lambda: 123.0)
    monkeypatch.setattr(pygame.event, "clear", lambda events: cleared.extend(events))

    app._handle_resume("test")

    assert app.pointer_down is False
    assert app.current_stroke is None
    assert app.recall_strip_drag_last_y is None
    assert app.recall_pressed_index is None
    assert app.recall_drag_distance == 0
    assert app.last_autosave == 0.0  # Input noise must not postpone a due save.
    assert pygame.MOUSEMOTION in cleared
    assert pygame.MOUSEBUTTONDOWN in cleared
    assert pygame.MOUSEBUTTONUP in cleared
    assert pygame.MOUSEWHEEL in cleared
