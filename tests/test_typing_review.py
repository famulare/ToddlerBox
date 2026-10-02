import json
from pathlib import Path

import pygame
import pytest

from toddlerbox.typing.app import TypingApp, _load_recent_sessions


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    config = tmp_path / "config.yaml"
    config.write_text(f"data_root: {tmp_path / 'data'}\n")
    monkeypatch.setenv("KIDBOX_CONFIG", str(config))
    pygame.init()
    surface = pygame.display.set_mode((1024, 768))
    application = TypingApp(screen=surface)
    pygame.event.clear()
    yield application
    pygame.quit()


def record(char="A", **extra):
    return {"rich_lines": [[{"char": char, "size": 25, "style": "plain"}]], **extra}


def test_idle_and_cursor_motion_reuse_layout_without_measuring_fonts(app, monkeypatch):
    for char in "hello world":
        app._insert_char(char)
    original = app._get_font
    measurements = []

    def get_font(*args):
        measurements.append(args)
        return original(*args)

    monkeypatch.setattr(app, "_get_font", get_font)
    layout = app._build_visual_lines()
    assert measurements
    measurements.clear()
    app._move_cursor_left()
    for _ in range(10):
        assert app._build_visual_lines() is layout
    assert measurements == []


def test_edits_undo_clear_and_width_invalidate_layout(app):
    app._insert_char("A")
    first = app._build_visual_lines()
    app._insert_char("B")
    second = app._build_visual_lines()
    assert second is not first
    assert [glyph.char for glyph in second[0].glyphs] == ["A", "B"]
    app._undo()
    third = app._build_visual_lines()
    assert [glyph.char for glyph in third[0].glyphs] == ["A"]
    app._insert_char("\n")
    assert len(app._build_visual_lines()) == 2
    app._undo()
    assert len(app._build_visual_lines()) == 1
    before_resize = app._build_visual_lines()
    app.text_rect.width = 10
    assert app._build_visual_lines() is not before_resize
    app._clear_text()
    assert app._build_visual_lines()[0].glyphs == []


def test_empty_row_height_tracks_insertion_style_and_cursor(app):
    app._insert_char("\n")
    layout = app._build_visual_lines()
    app._set_text_font(size=100)
    enlarged = app._build_visual_lines()
    assert enlarged[1].height > layout[1].height
    app._move_cursor_up()
    moved = app._build_visual_lines()
    assert moved[0].height == enlarged[1].height
    assert moved[1].height == layout[1].height


def test_recall_only_opens_newest_requested_archives(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    archive.mkdir()
    for i in range(10):
        (archive / f"{i:03}.json").write_text(json.dumps(record(str(i))))
    legacy = tmp_path / "sessions.jsonl"
    legacy.write_text(json.dumps(record("L")))
    original_open = Path.open
    opened = []

    def tracked_open(path, *args, **kwargs):
        opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked_open)
    assert [item.preview for item in _load_recent_sessions(legacy, limit=2)] == ["9", "8"]
    assert opened == [archive / "009.json", archive / "008.json"]


def test_recall_legacy_tail_keeps_complete_recent_records(tmp_path, monkeypatch):
    path = tmp_path / "sessions.jsonl"
    newest = (json.dumps(record("Z")) + "\n").encode()
    path.write_bytes(b"{\"old\":\"" + b"x" * 1000 + b"\"}\n" + newest)
    monkeypatch.setattr("toddlerbox.typing.app.RECALL_READ_BYTES", len(newest) + 20)
    assert [item.preview for item in _load_recent_sessions(path)] == ["Z"]


def test_recall_skips_future_versions_without_changing_archives(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    future = archive / "2.json"
    future.write_text(json.dumps(record("F", version=2)))
    saved = future.read_bytes()
    (archive / "1.json").write_text(json.dumps(record("A", version=1)))
    assert [item.preview for item in _load_recent_sessions(tmp_path / "sessions.jsonl")] == ["A"]
    assert future.read_bytes() == saved


def test_future_current_is_preserved_and_rollback_work_uses_durable_sidecar(app):
    primary = app.current_path
    future = json.dumps({"version": 2, "future_document": "precious work"}).encode()
    primary.write_bytes(future)
    reopened = TypingApp(screen=app.screen)
    assert reopened.current_path.name == "current-v1.json"
    reopened._insert_char("B")
    assert reopened._save_current()
    assert primary.read_bytes() == future
    assert not list(app.typing_dir.glob("corrupt-*.json"))
    again = TypingApp(screen=app.screen)
    assert again.text_lines == ["B"]
    assert primary.read_bytes() == future


@pytest.mark.parametrize("options", [{"max_archives": 0}, {"max_archive_bytes": 1}])
def test_typing_capacity_refuses_new_without_losing_work(app, options):
    app.config["typing"] = options
    app._insert_char("A")
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=app.new_button.rect.center, button=1))
    pygame.event.post(pygame.event.Event(pygame.QUIT))
    app.run(quit_on_exit=False)
    assert app.text_lines == ["A"]
    assert TypingApp(screen=app.screen).text_lines == ["A"]
    assert not list((app.typing_dir / "archive").glob("*.json"))


def test_full_archive_capacity_keeps_existing_archives_and_current_work(app):
    app.config["typing"] = {"max_archives": 1}
    app._insert_char("A")
    assert app._archive_session()
    archive = next((app.typing_dir / "archive").glob("*.json"))
    original = archive.read_bytes()
    app._insert_char("B")
    assert not app._archive_session()
    assert app.text_lines == ["AB"]
    assert archive.read_bytes() == original


def test_touch_generated_mouse_event_does_not_apply_undo_twice(app):
    for char in "abc":
        app._insert_char(char)
    x, y = app.undo_button.rect.center
    pygame.event.post(pygame.event.Event(pygame.FINGERDOWN, finger_id=1, touch_id=2,
                                        x=x / app.screen_rect.width, y=y / app.screen_rect.height))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(x, y), button=1, touch=True))
    pygame.event.post(pygame.event.Event(pygame.QUIT))
    app.run(quit_on_exit=False)
    assert app.text_lines == ["ab"]


@pytest.mark.parametrize("exit_kind", ["quit", "home", "escape"])
def test_exit_discards_later_edits_in_fetched_batch(app, exit_kind):
    app._insert_char("A")
    pygame.event.clear()
    if exit_kind == "quit":
        event = pygame.event.Event(pygame.QUIT)
    elif exit_kind == "home":
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=app.home_button.rect.center, button=1)
    else:
        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode="")
    pygame.event.post(event)
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_z, mod=0, unicode="z"))
    app.run(quit_on_exit=False)
    assert app.text_lines == ["A"]
    assert TypingApp(screen=app.screen).text_lines == ["A"]


def test_focus_reset_discards_remaining_pointer_batch(app, monkeypatch):
    app._insert_char("A")
    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.WINDOWFOCUSGAINED))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=app.undo_button.rect.center, button=1))
    frames = 0

    def stop_after_frame():
        nonlocal frames
        frames += 1
        if frames == 2:
            raise RuntimeError("frame completed")

    monkeypatch.setattr(app, "_render", stop_after_frame)
    with pytest.raises(RuntimeError, match="frame completed"):
        app._run()
    assert app.text_lines == ["A"]


def test_low_disk_reserve_refuses_archive_but_allows_current_save(app, monkeypatch):
    app._insert_char("A")
    monkeypatch.setattr("toddlerbox.typing.app.has_archive_reserve", lambda *args: False)
    assert not app._archive_session()
    assert app.text_lines == ["A"]
    assert app._save_current()
    assert TypingApp(screen=app.screen).text_lines == ["A"]
