"""Typing input stays bounded and renderable; older saves are salvaged, never lost."""
import json

import pygame
import pytest

from toddlerbox.typing.app import MAX_GLYPHS, MAX_LINES, Glyph, TypingApp, _load_recent_sessions


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


def glyph(char, size=25, style="plain"):
    return {"char": char, "size": size, "style": style}


def write_current(tmp_path, lines):
    typing_dir = tmp_path / "data/typing"
    typing_dir.mkdir(parents=True, exist_ok=True)
    raw = json.dumps({"version": 1, "rich_lines": lines, "cursor": [0, 0], "size": 25, "style": "plain"},
                     ensure_ascii=False)
    (typing_dir / "current.json").write_text(raw, encoding="utf-8")
    return typing_dir, raw


@pytest.mark.parametrize("text", ["é", "͏", "️", "᠋", "\t", "\x07"])
def test_unrenderable_or_multi_code_point_input_is_ignored(screen, text):
    app = TypingApp(screen=screen)
    app._insert_char("a")
    app._insert_char(text)
    assert app.text_lines == ["a"]
    app._render()


def test_real_key_events_with_combined_unicode_do_not_reach_the_document(screen):
    app = TypingApp(screen=screen)
    pygame.event.clear()
    for unicode in ["h", "é", "͏", "i"]:
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=0, unicode=unicode))
    pygame.event.post(pygame.event.Event(pygame.QUIT))
    app.run(quit_on_exit=False)
    reopened = TypingApp(screen=screen)
    assert reopened.text_lines == ["hi"]


def test_new_input_stops_at_the_glyph_cap_and_resumes_after_deleting(screen):
    app = TypingApp(screen=screen)
    app.rich_lines = [[Glyph("x", 25, "plain") for _ in range(MAX_GLYPHS)]]
    app._sync_all_text_lines()
    app.cursor_row, app.cursor_col = 0, MAX_GLYPHS
    app._insert_char("y")
    assert app._glyph_count() == MAX_GLYPHS and not app.text_lines[0].endswith("y")
    app._delete_backward()
    app._insert_char("y")
    assert app.text_lines[0].endswith("y")


def test_new_lines_stop_at_the_line_cap(screen):
    app = TypingApp(screen=screen)
    for _ in range(MAX_LINES + 10):
        app._insert_char("\n")
    assert len(app.rich_lines) == MAX_LINES


def test_existing_oversized_document_is_never_truncated(screen, tmp_path):
    lines = [[glyph("z") for _ in range(1000)] for _ in range(MAX_GLYPHS // 1000 + 5)]
    write_current(tmp_path, lines)
    app = TypingApp(screen=screen)
    assert app._glyph_count() == sum(map(len, lines))
    app.cursor_row, app.cursor_col = 0, len(app.rich_lines[0])
    app._insert_char("q")
    assert app._glyph_count() == sum(map(len, lines))
    app._delete_backward()
    assert app._save_current()
    assert TypingApp(screen=screen)._glyph_count() == sum(map(len, lines)) - 1


def test_bad_glyphs_are_dropped_while_the_exact_original_is_preserved(screen, tmp_path):
    lines = [[glyph("o"), glyph("k"), glyph("é"), glyph("!", size=5000), "junk"], "junk-line", [glyph("2")]]
    typing_dir, raw = write_current(tmp_path, lines)
    app = TypingApp(screen=screen)
    assert app.text_lines == ["ok", "2"]
    assert [p.read_text(encoding="utf-8") for p in typing_dir.glob("corrupt-*.json")] == [raw]
    assert app._save_current()
    assert TypingApp(screen=screen).text_lines == ["ok", "2"]


def test_zero_advance_glyphs_from_older_saves_render_without_crashing(screen, tmp_path):
    write_current(tmp_path, [[glyph("a"), glyph("͏"), glyph("b")], [glyph("️")]])
    app = TypingApp(screen=screen)
    app._render()
    assert app.text_lines == ["a͏b", "️"]


def test_recall_preview_survives_one_bad_glyph(screen, tmp_path):
    typing_dir = tmp_path / "data/typing"
    (typing_dir / "archive").mkdir(parents=True)
    record = {"version": 1, "timestamp": "2026-10-23T10:00:00", "rich_lines": [[glyph("h"), glyph("ab"), glyph("i")]]}
    (typing_dir / "archive/1.json").write_text(json.dumps(record))
    app = TypingApp(screen=screen)
    assert [s.preview for s in _load_recent_sessions(app.sessions_path)] == ["hi"]
