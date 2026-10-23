"""Real short-write, orphan-temporary and quarantine faults for child work."""
import io
import json
import os
import subprocess
import sys
import textwrap

import pygame
import pytest
from PIL import Image

from toddlerbox.paint.app import PaintApp, _encode_png
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


def png_bytes(color, size=(40, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def decoded(data):
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGB").tobytes()


@pytest.mark.skipif(not hasattr(__import__("resource"), "RLIMIT_FSIZE"), reason="needs RLIMIT_FSIZE")
def test_kernel_short_write_never_replaces_previous_complete_save(tmp_path):
    # RLIMIT_FSIZE makes write() fail part-way, the same path as ENOSPC/EIO.
    # Run in a child so the limit cannot affect pytest's own files.
    script = textwrap.dedent(f"""
        import os, random, resource, signal
        from pathlib import Path
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        import pygame
        from toddlerbox.paint.app import _save_pixels_atomic
        from toddlerbox.runtime.persistence import publish_new_bytes, write_bytes
        directory = Path({str(tmp_path)!r})
        random.seed(0)
        pixels = bytes(random.randrange(256) for _ in range(300 * 200 * 3))
        latest = directory / "latest.png"
        _save_pixels_atomic(pixels, (300, 200), latest)
        (directory / "good.bin").write_bytes(latest.read_bytes())
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (latest.stat().st_size // 3, resource.RLIM_INFINITY))
        results = []
        for name, action in [
            ("paint", lambda: _save_pixels_atomic(bytes(reversed(pixels)), (300, 200), latest)),
            ("typing", lambda: write_bytes(directory / "current.json", b"x" * 200000)),
            ("archive", lambda: publish_new_bytes(directory / "archive.png", b"y" * 200000)),
        ]:
            try:
                action()
                results.append(name + ":returned")
            except OSError:
                results.append(name + ":raised")
        print(" ".join(results))
    """)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1].split() == ["paint:raised", "typing:raised", "archive:raised"]
    latest = tmp_path / "latest.png"
    assert latest.read_bytes() == (tmp_path / "good.bin").read_bytes()
    Image.open(latest).load()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["good.bin", "latest.png"]


def test_in_memory_encoder_matches_previous_pygame_pixels(screen, tmp_path):
    surface = pygame.Surface((64, 48))
    surface.fill((255, 255, 255))
    pygame.draw.circle(surface, (200, 30, 90), (20, 20), 12)
    pygame.draw.line(surface, (10, 120, 200), (0, 47), (63, 0), 5)
    previous = tmp_path / "previous.png"
    pygame.image.save(surface, str(previous))
    current = _encode_png(pygame.image.tobytes(surface, "RGB"), surface.get_size())
    assert decoded(current) == decoded(previous.read_bytes())


def test_new_archive_names_never_replace_existing_work(tmp_path):
    first = persistence.publish_new_bytes(tmp_path / "2026-10-23_120000.png", b"first")
    second = persistence.publish_new_bytes(tmp_path / "2026-10-23_120000.png", b"second")
    assert first.name == "2026-10-23_120000.png"
    assert second.name == "2026-10-23_120000_1.png"
    assert first.read_bytes() == b"first" and second.read_bytes() == b"second"
    assert not (tmp_path / ".2026-10-23_120000.tmp.png").exists()


def test_paint_recovers_complete_orphan_as_recall_archive_before_reuse(screen, tmp_path):
    paint = tmp_path / "data/paint"
    paint.mkdir(parents=True)
    (paint / "latest.png").write_bytes(png_bytes("red"))
    newer = png_bytes("blue")
    (paint / ".latest.tmp.png").write_bytes(newer)
    app = PaintApp(screen=screen)
    recovered = [p for p in app._recall_archives() if p.name.startswith("recovered-")]
    assert [p.read_bytes() for p in recovered] == [newer]
    assert not (paint / ".latest.tmp.png").exists()
    assert app.canvas_surface.get_at((5, 5))[:3] == (255, 0, 0)


def test_paint_quarantines_truncated_orphan_and_keeps_it_out_of_recall(screen, tmp_path):
    paint = tmp_path / "data/paint"
    paint.mkdir(parents=True)
    partial = png_bytes("blue")[:40]
    (paint / ".2026-10-23_120000.tmp.png").write_bytes(partial)
    app = PaintApp(screen=screen)
    corrupt = list(paint.glob("corrupt-*.png"))
    assert [p.read_bytes() for p in corrupt] == [partial]
    assert app._recall_archives() == []


def test_paint_never_overwrites_unreadable_save_it_cannot_quarantine(screen, tmp_path):
    paint = tmp_path / "data/paint"
    paint.mkdir(parents=True)
    (paint / "latest.png").write_bytes(b"damaged")
    os.chmod(paint, 0o500)
    try:
        app = PaintApp(screen=screen)
        app.canvas_surface.fill((1, 80, 120))
        app._mark_canvas_changed()
        assert not app._autosave_latest()
        assert app._save_for_control() is False
    finally:
        os.chmod(paint, 0o700)
    assert (paint / "latest.png").read_bytes() == b"damaged"


def test_typing_recovers_orphans_and_ignores_temporaries_in_archive(screen, tmp_path):
    typing_dir = tmp_path / "data/typing"
    (typing_dir / "archive").mkdir(parents=True)
    document = {"version": 1, "rich_lines": [[{"char": c, "size": 25, "style": "plain"} for c in "hi"]],
                "cursor": [0, 2], "size": 25, "style": "plain"}
    (typing_dir / ".current.tmp.json").write_text(json.dumps(document))
    (typing_dir / "archive/.17.tmp.json").write_text("{partial")
    app = TypingApp(screen=screen)
    assert [s.preview for s in _load_recent_sessions(app.sessions_path)] == ["hi"]
    assert len(list(typing_dir.glob("archive/recovered-*.json"))) == 1
    assert [p.read_text() for p in typing_dir.glob("archive/corrupt-*.json")] == ["{partial"]
    assert not list(typing_dir.glob("**/.*.tmp.json"))


@pytest.mark.parametrize("payload", [
    json.dumps({"version": 1, "rich_lines": [[]], "cursor": {}}),
    "[" * 200000 + "]" * 200000,
])
def test_typing_hostile_current_document_is_preserved_without_crash_loop(screen, tmp_path, payload):
    typing_dir = tmp_path / "data/typing"
    typing_dir.mkdir(parents=True)
    (typing_dir / "current.json").write_text(payload)
    app = TypingApp(screen=screen)
    assert app.text_lines == [""]
    assert [p.read_text() for p in typing_dir.glob("corrupt-*.json")] == [payload]
    assert app._save_current()
    TypingApp(screen=screen)


def test_typing_never_overwrites_unreadable_document_it_cannot_quarantine(screen, tmp_path):
    typing_dir = tmp_path / "data/typing"
    (typing_dir / "archive").mkdir(parents=True)
    (typing_dir / "current.json").write_text("{broken")
    os.chmod(typing_dir, 0o500)
    try:
        app = TypingApp(screen=screen)
        app._insert_char("A")
        assert not app._save_current()
        assert app._save_for_control() is False
    finally:
        os.chmod(typing_dir, 0o700)
    assert (typing_dir / "current.json").read_text() == "{broken"
