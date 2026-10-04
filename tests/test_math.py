from dataclasses import replace
import random
import socket
from unittest.mock import Mock

import pygame
import pytest

from toddlerbox.math.app import MathApp
from toddlerbox.math.model import Example, MODES, Options, choose_next, options_from_config, prompt_distribution
from toddlerbox.math.visuals import draw_quantity, frame_geometry
from toddlerbox.runtime import control, health
from toddlerbox.ui import theme


def test_full_range_defaults_and_per_number_weights_are_exact():
    options = options_from_config({}, Mock())
    assert options == Options(100, 12, "numerals")
    rows = dict(prompt_distribution("numerals", options))
    assert set(rows) == {(n, 0) for n in range(101)}
    assert all(rows[n, 0] == 12 for n in range(21))
    assert all(rows[n, 0] == 1 for n in range(21, 101))
    assert sum(rows[n, 0] for n in range(21)) == 252
    assert sum(rows.values()) == 332


@pytest.mark.parametrize("mode", ["addition", "subtraction"])
def test_all_arithmetic_prompts_and_total_probabilities(mode):
    rows = prompt_distribution(mode, Options())
    assert len(rows) == 5151
    totals = {}
    for (a, b), weight in rows:
        example = Example(mode, a, b)
        assert 0 <= example.result <= 100
        total = a+b if mode == "addition" else a
        totals[total] = totals.get(total, 0)+weight
    assert set(totals) == set(range(101))
    for total, weight in totals.items():
        assert weight == pytest.approx(12 if total <= 20 else 1)


@pytest.mark.parametrize("mode", MODES)
def test_repeat_exclusion_preserves_conditional_relative_weights(mode):
    current = Example(mode, 3, 2 if mode in ("addition", "subtraction") else 0)
    options = Options(max_number=7)
    original = dict(prompt_distribution(mode, options))
    conditioned = dict(prompt_distribution(mode, options, replace(current, motif="egg")))
    del original[current.a, current.b]
    assert conditioned == original
    if mode == "addition":
        assert (2, 3) in conditioned  # Ordered prompts can teach commutativity.


def test_weighted_draw_excludes_numerical_repeat_not_just_art_and_has_no_retry():
    rng = Mock()
    rng.choices.side_effect = lambda candidates, **kwargs: [candidates[-1]]
    rng.choice.side_effect = lambda candidates: candidates[0]
    old = Example("addition", 0, 0, "fish")
    new = choose_next("addition", Options(), rng, old)
    candidates = rng.choices.call_args.args[0]
    assert (0, 0) not in candidates and new.identity != old.identity
    assert new.a+new.b == 100
    assert rng.choices.call_count == 1
    assert choose_next("count", Options(max_number=0), rng, Example("count", 0)).a == 0


@pytest.mark.parametrize("raw", [{"max_number": -1}, {"max_number": True}, {"max_number": 101},
                                  {"low_number_weight": 0}, {"low_number_weight": float("nan")},
                                  {"mode": []}, None])
def test_invalid_parent_configuration_has_quiet_bounded_defaults(raw):
    assert options_from_config({"math": raw}, Mock()) == Options()


@pytest.mark.parametrize("mode,a,b", [("addition", 100, 1), ("subtraction", 1, 2),
                                      ("numerals", 4, 1), ("count", True, 0)])
def test_invalid_examples_rejected(mode, a, b):
    with pytest.raises(ValueError):
        Example(mode, a, b)


def test_ten_frames_cover_exactly_the_quantity_without_escape():
    for area in (pygame.Rect(0, 0, 220, 330), pygame.Rect(8, 9, 360, 350)):
        for n in range(101):
            frames, cells, size = frame_geometry(n, area)
            assert len(frames) == max(1, (n+9)//10)
            assert len(cells) == n and size >= 1
            assert all(area.contains(frame) for frame in frames)
            assert len({tuple(cell) for cell in cells}) == n
            assert all(any(frame.contains(cell) for frame in frames) for cell in cells)
    frames, cells, _ = frame_geometry(23, pygame.Rect(0,0,360,350))
    assert [sum(frame.contains(cell) for cell in cells) for frame in frames] == [10,10,3]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    monkeypatch.delenv("TODDLERBOX_APP_CONTROL", raising=False)
    monkeypatch.setattr(control, "_channel", None)
    pygame.init()
    screen = pygame.display.set_mode((800,600))
    value = MathApp(screen, screen.get_rect(), pygame.time.Clock(),
                    config={"data_root": str(tmp_path)}, rng=random.Random(17))
    yield value
    value.art.close()
    pygame.quit()


def select(app, mode, a, b=0, revealed=False):
    app.mode = mode
    app.example = Example(mode, a, b, "cat")
    app.revealed = revealed


def pixels(app, rect=None):
    surface = app.screen if rect is None else app.screen.subsurface(rect)
    return pygame.image.tobytes(surface, "RGB")


def tap(app, pos):
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        result = app.handle_event(pygame.event.Event(kind, button=1, pos=pos))
    return result


def test_hidden_objects_neither_leak_quantity_nor_look_like_zero(app):
    select(app, "numerals", 0)
    app.render()
    hidden_zero = pixels(app, app.body_rect)
    select(app, "numerals", 100)
    app.render()
    assert pixels(app, app.body_rect) == hidden_zero
    select(app, "numerals", 0, revealed=True)
    app.render()
    assert pixels(app, app.body_rect) != hidden_zero


def test_count_question_hides_number_but_displays_objects(app):
    select(app, "count", 1)
    app.render()
    question, body = pixels(app, app.question_rect), pixels(app, app.body_rect)
    select(app, "count", 100)
    app.render()
    assert pixels(app, app.question_rect) == question
    assert pixels(app, app.body_rect) != body
    tap(app, app.question_rect.center)
    app.render()
    assert app._question() == "100" and pixels(app, app.question_rect) != question


def test_subtraction_removes_only_final_positions_and_result_matches_survivors(app):
    select(app, "subtraction", 23, 8, revealed=True)
    left = pygame.Rect(0,0,360,350)
    normal = pygame.Surface(left.size)
    normal.fill(theme.PANEL)
    removed = normal.copy()
    cells = draw_quantity(normal, 23, left, app.art, "cat")
    draw_quantity(removed, 23, left, app.art, "cat", removed=8)
    changed = [i for i, cell in enumerate(cells)
               if pygame.image.tobytes(normal.subsurface(cell), "RGB") !=
               pygame.image.tobytes(removed.subsurface(cell), "RGB")]
    assert changed == list(range(15,23))
    assert app.example.result == 15
    result_cells = draw_quantity(normal, app.example.result, left, app.art, "cat")
    assert len(result_cells) == 15
    # Removed art changes actual pixels, keeping a visible muted cancellation mark.
    assert app.art.scaled("cat", 32).get_alpha() == 255
    assert app.art.scaled("cat", 32, True).get_alpha() == 100


@pytest.mark.parametrize("size", [(800,600), (1366,768)])
def test_dense_arithmetic_is_readable_and_reveal_does_not_change_inputs(app, size):
    app.screen = pygame.display.set_mode(size)
    replacement = MathApp(app.screen, app.screen.get_rect(), app.clock, config=app.config)
    try:
        select(replacement, "addition", 50, 50)
        replacement.render()
        inputs = [pixels(replacement, p) for p in replacement.quantity_panels()[:2]]
        hidden = pixels(replacement, replacement.quantity_panels()[-1])
        replacement.reveal()
        replacement.render()
        assert inputs == [pixels(replacement, p) for p in replacement.quantity_panels()[:2]]
        assert hidden != pixels(replacement, replacement.quantity_panels()[-1])
        for panel in replacement.quantity_panels():
            assert replacement.rect.contains(panel)
            assert frame_geometry(100, panel.inflate(-12,-20))[2] >= 18
    finally:
        replacement.art.close()


def test_objects_inert_and_reveal_is_idempotent_then_next_and_mode_reset(app):
    select(app, "numerals", 7)
    tap(app, app.body_rect.center)
    assert not app.revealed
    tap(app, app.question_rect.center)
    assert app.revealed
    old = app.example
    tap(app, app.question_rect.center)
    assert app.example == old and app.revealed
    tap(app, app.next_rect.center)
    assert not app.revealed and app.example.identity != old.identity
    tap(app, app.mode_rect.center)
    assert app.mode == "count" and not app.revealed
    assert tap(app, app.home_rect.center) is False


def test_focus_unowned_release_and_drag_do_not_reveal(app):
    select(app, "numerals", 7)
    pos = app.question_rect.center
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos))
    assert not app.revealed
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
    app.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos))
    assert not app.revealed and app.pointer.owner is None
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(pos[0]+30,pos[1])))
    assert not app.revealed


def test_singleton_hides_next_but_modes_still_work(app):
    app.options = Options(max_number=0)
    select(app, "numerals", 0)
    assert not app.can_next and app._target(app.next_rect.center) is None
    tap(app, app.mode_rect.center)
    assert app.mode == "count" and app.example.a == 0


def test_bounded_art_cache_and_all_missing_art_returns_home(app, tmp_path):
    for size in range(1,101):
        for name in app.art.sources:
            app.art.scaled(name,size)
    assert app.art.scaled.cache_info().currsize <= 48
    empty = MathApp(app.screen, app.rect, app.clock, config=app.config, library=tmp_path)
    assert empty.example is None
    empty.run()


@pytest.mark.parametrize("kind", ["oversized", "wrong-format"])
def test_bad_art_headers_are_rejected_before_sdl_decoding(app, tmp_path, monkeypatch, kind):
    from PIL import Image
    from toddlerbox.math.visuals import Illustrations
    if kind == "oversized":
        Image.new("RGBA", (2048,1024), "red").save(tmp_path/"cat.png")
    else:
        Image.new("RGB", (64,64), "red").save(tmp_path/"cat.png", format="BMP")
    loader = Mock(side_effect=AssertionError("Unsafe image reached SDL"))
    monkeypatch.setattr(pygame.image, "load", loader)
    art = Illustrations(tmp_path)
    assert not art.sources
    loader.assert_not_called()
    art.close()


def test_corrupt_png_crc_skips_bad_motif_and_retains_good_art(app, tmp_path, monkeypatch):
    from PIL import Image
    from toddlerbox.math.visuals import Illustrations
    path = tmp_path/"cat.png"
    Image.new("RGBA", (64,64), "red").save(path)
    data = bytearray(path.read_bytes())
    data[data.index(b"IDAT")+4] ^= 1
    path.write_bytes(data)
    Image.new("RGBA", (64,64), "green").save(tmp_path/"egg.png")
    loader = Mock(wraps=pygame.image.load)
    monkeypatch.setattr(pygame.image, "load", loader)
    art = Illustrations(tmp_path)
    assert set(art.sources) == {"egg"}
    loader.assert_called_once_with(str(tmp_path/"egg.png"))
    art.close()


def test_actual_loop_services_no_work_save_overlay_and_health_before_flip(app, monkeypatch):
    calls = []
    class Receipt:
        received_at = 10
        def service(self, save_current=None):
            assert save_current is None
            calls.append("service")
        def clock(self):
            return 10
    monkeypatch.setattr(control, "_channel", Receipt())
    app.render()
    before = pixels(app)
    events = iter([[], [pygame.event.Event(pygame.QUIT)]])
    monkeypatch.setattr(pygame.event, "get", lambda: next(events))
    monkeypatch.setattr(health, "stopping", lambda: False)
    monkeypatch.setattr(health, "frame_complete", lambda: calls.append("health"))
    monkeypatch.setattr(pygame.display, "flip", lambda: calls.append("flip"))
    app.run()
    assert calls == ["service", "flip", "health"]
    assert pixels(app) != before
    assert app.pointer.owner is None


@pytest.mark.skipif(not hasattr(socket, "SO_PASSCRED"), reason="Linux authenticated app IPC")
def test_authenticated_save_request_uses_existing_no_work_ack(app):
    import os
    import struct
    # Exercise production service with credential data; syscall path is covered
    # by existing Linux integration tests, not weakened for the Mac trial.
    channel = object.__new__(control.AppChannel)
    channel.address = "/test-controller"
    channel.clock = lambda: 1
    channel.serviced = []
    channel.received_at = float("-inf")
    nonce = b"a"*32
    message = b"save-current:"+nonce
    channel.socket = Mock()
    channel.socket.recvmsg.side_effect = [(message, [(socket.SOL_SOCKET, socket.SCM_CREDENTIALS,
                                           struct.pack("3i", os.getpid(), 0, 0))], 0, None), BlockingIOError()]
    channel.service()
    channel.socket.sendto.assert_called_once_with(b"save-result:"+nonce+b":ok", "/test-controller")
