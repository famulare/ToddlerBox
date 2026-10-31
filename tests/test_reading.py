from dataclasses import replace
import json
from pathlib import Path
import random
import shutil
from unittest.mock import Mock

import pygame
import pytest

from toddlerbox.reading.catalog import Card, Cue, Options, RATE, Speech, load_catalog, options_from_config
from toddlerbox.reading.playback import SpeechAssetError, SpeechDeviceError, SpeechPlayer
from toddlerbox.reading.selection import choose_next

ASSETS = Path(__file__).resolve().parents[1] / "assets/reading"


class Audio:
    def __init__(self):
        self.pos, self.playing, self.started = 0, False, []
        self.error = None

    def play(self, speech, volume):
        if self.error:
            raise self.error
        self.started.append(speech.path.name)
        self.pos, self.playing = 0, True

    def position(self):
        return self.pos

    def busy(self):
        return self.playing

    def stop(self):
        self.playing = False


@pytest.fixture
def card():
    sequence = Speech(Path("sequence.wav"), RATE, (Cue(0, 10000, 0), Cue(10000, 20000, 1), Cue(20000, RATE, -1)))
    replay = Speech(Path("whole.wav"), RATE // 2, (Cue(0, RATE // 2, -1),))
    return Card("cat", "words", "cat", ("c", "a", "t"), None, sequence, replay)


def test_uniform_candidate_set_excludes_current_and_deduplicates_without_rotation(card):
    cards = [card, replace(card, id="map"), replace(card, id="dog"), replace(card, id="map")]
    rng = Mock()
    rng.choice.side_effect = lambda candidates: candidates[0]
    assert choose_next(cards, "cat", rng).id == "map"
    assert [c.id for c in rng.choice.call_args.args[0]] == ["map", "dog"]
    assert choose_next(cards, "map", rng).id == "cat"  # A recent card can return.
    assert choose_next([card], "cat", rng) is None
    assert choose_next([], None, rng) is None


def test_picture_waits_for_completion_and_taps_do_not_queue(card):
    audio, now = Audio(), [0.0]
    player = SpeechPlayer(Mock(), audio=audio, clock=lambda: now[0])
    player.select(card)
    player.play(whole_word=True)
    assert audio.started == ["whole.wav"]  # Whole word is now a deliberate independent action.
    player.cancel()
    audio.started.clear()
    player.play()
    player.play()
    assert audio.started == ["sequence.wav"] and not player.revealed
    audio.pos = 300
    player.update()
    assert player.active_unit == 1
    audio.pos = 970
    player.update()
    assert player.active_unit == -1 and not player.revealed
    audio.pos, audio.playing = -1, False
    player.update()
    assert player.revealed and player.active_unit is None
    player.play(whole_word=True)
    assert audio.started[-1] == "whole.wav" and player.revealed


def test_next_and_focus_cancel_old_speech_without_stale_reveal(card):
    audio = Audio()
    player = SpeechPlayer(Mock(), audio=audio)
    player.select(card)
    player.play()
    player.select(replace(card, id="dog"))
    audio.pos, audio.playing = 10000, False
    player.update()
    assert player.card.id == "dog" and not player.revealed
    player.play()
    player.cancel()
    player.update()
    assert not player.revealed and not audio.playing and player.active_unit is None


def test_device_failure_can_be_retried_but_corrupt_card_is_bounded(card):
    audio = Audio()
    player = SpeechPlayer(Mock(), audio=audio)
    player.select(card)
    audio.error = SpeechDeviceError()
    player.play()
    assert player.state == "unavailable" and not player.failed and not player.revealed
    audio.error = None
    player.play()
    assert player.state == "playing"
    player.cancel()
    audio.error = SpeechAssetError()
    player.play()
    assert player.failed == {card.id}
    audio.error = None
    player.play()
    assert player.state == "unavailable"


def test_early_end_and_stuck_stream_never_reveal(card):
    audio, now = Audio(), [0.0]
    player = SpeechPlayer(Mock(), audio=audio, clock=lambda: now[0])
    player.select(card)
    player.play()
    audio.playing = False
    player.update()
    assert player.state == "unavailable" and not player.revealed
    player.play()
    now[0] = 3
    player.update()
    assert not audio.playing and player.state == "unavailable" and not player.revealed


def test_short_recording_that_never_started_does_not_reveal(card):
    audio = Audio()
    player = SpeechPlayer(Mock(), audio=audio)
    short = Speech(Path("short.wav"), RATE // 20, (Cue(0, RATE // 20, -1),))
    player.select(replace(card, sequence=short))
    player.play()
    audio.playing = False
    player.update()
    assert player.state == "unavailable" and not player.revealed


@pytest.mark.parametrize("bad", [None, [], "numbers", {"volume": float("nan"), "number_max": True},
                                  {"word_sets": [{"bad": 1}], "mode": []}])
def test_invalid_parent_settings_fall_back_without_crashing(bad):
    assert options_from_config({"reading": bad}, Mock()) == Options()


def test_bad_card_is_isolated_and_asset_paths_cannot_escape(tmp_path):
    catalog = json.loads((ASSETS / "catalog.json").read_text())
    valid = catalog["cards"][0]
    for relative in [valid["image"], valid["sequence"]["path"], valid["replay"]["path"]]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ASSETS / relative, target)
    bad = dict(valid, id="escape", image="../outside.png")
    broken_units = dict(valid, id="wrong-units", units=["c", "t"])
    duplicate = dict(valid)
    catalog["cards"] = [valid, bad, broken_units, duplicate]
    (tmp_path / "catalog.json").write_text(json.dumps(catalog))
    assert [c.id for c in load_catalog(tmp_path, Options(), Mock())] == [valid["id"]]
    wav = tmp_path / valid["sequence"]["path"]
    wav.write_bytes(wav.read_bytes()[:-200])
    assert load_catalog(tmp_path, Options(), Mock()) == []


@pytest.fixture
def scene(tmp_path, monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    from toddlerbox.reading.app import ReadingApp
    screen = pygame.display.set_mode((1024, 600))
    audio = Audio()
    app = ReadingApp(screen, screen.get_rect(), pygame.time.Clock(),
                     config={"data_root": str(tmp_path)}, audio=audio, rng=random.Random(7))
    yield app, audio
    app.close()
    pygame.quit()


def click(app, pos):
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        app.handle_event(pygame.event.Event(kind, pos=pos, button=1, touch=False))


def _finish_previews(app):
    for _ in range(len(app.cards) + 2):
        app._service_thumbnails()
        if app._thumbnail_future is None:
            return
        app._thumbnail_future.result(timeout=5)
    raise AssertionError("Reading preloading did not settle")


def test_reading_opens_pictures_and_preloads_deck_without_drawing_io(scene, monkeypatch):
    app, _ = scene
    assert app.rail_images
    _finish_previews(app)
    assert len(app.thumbnails) == len(app.cards)
    app.render()  # Warm the shared Home glyph before guarding rail rendering.
    monkeypatch.setattr(pygame.image, "load", Mock(side_effect=AssertionError("IO in render")))
    for offset in range(0, len(app.cards)*76, 76):
        app.rail_offset = offset
        app.render()


def test_slow_reading_preload_never_blocks_or_releases_finger(scene, monkeypatch):
    import threading
    from toddlerbox.reading import app as module
    app, _ = scene
    entered, release = threading.Event(), threading.Event()
    original = module._thumbnail_pixels
    main_thread = threading.get_ident()

    def blocked(path):
        assert threading.get_ident() != main_thread
        entered.set()
        assert release.wait(5)
        return original(path)

    monkeypatch.setattr(module, "_thumbnail_pixels", blocked)
    app._service_thumbnails()
    try:
        assert entered.wait(2)
        pending = app._thumbnail_future
        selected = app.card.id
        x = app.rail.centerx / app.rect.w
        def finger(kind, y, identity=1):
            return pygame.event.Event(kind, x=x, y=y/app.rect.h, finger_id=identity, touch_id=1)
        app.handle_event(finger(pygame.FINGERDOWN, 400))
        for y in range(390, 199, -10):
            app._service_thumbnails()
            assert app._thumbnail_future is pending  # One job, no growing queue.
            app.handle_event(finger(pygame.FINGERMOTION, y))
            app.render()
        assert app.rail_offset == 200 and app.card.id == selected
        assert app.pointer.owner == ("finger", 1, 1)
        app.handle_event(finger(pygame.FINGERUP, 200, identity=2))
        assert app.pointer.owner == ("finger", 1, 1)
        release.set()
        pending.result(timeout=5)
        app._service_thumbnails()
        assert app.pointer.owner == ("finger", 1, 1)
        app.handle_event(finger(pygame.FINGERUP, 200))
        assert app.pointer.owner is None and app.card.id == selected
    finally:
        release.set()


def test_reading_preview_cache_is_bounded_and_reloads_after_scroll(scene):
    app, _ = scene
    app._thumbnail_limit = 8
    _finish_previews(app)
    assert len(app.thumbnails) == 8
    initial = set(app.thumbnails)
    app._scroll(2000)
    _finish_previews(app)
    assert len(app.thumbnails) == 8 and set(app.thumbnails) != initial
    app._scroll(-2000)
    _finish_previews(app)
    assert len(app.thumbnails) == 8 and set(app.thumbnails) == initial


def test_touch_emulation_second_finger_and_next_during_speech(scene):
    app, audio = scene
    center = app.word_rect.center
    for kind in (pygame.FINGERDOWN, pygame.FINGERUP):
        event = pygame.event.Event(kind, x=center[0]/1024, y=center[1]/600, finger_id=1, touch_id=1)
        app.handle_event(event)
        if kind == pygame.FINGERDOWN:
            # A second finger cannot take ownership or activate Next.
            app.handle_event(pygame.event.Event(kind, x=.94, y=.5, finger_id=2, touch_id=1))
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        app.handle_event(pygame.event.Event(kind, pos=center, button=1, touch=True))
    assert len(audio.started) == 1
    first = app.card.id
    click(app, app.next_rect.center)
    assert app.card.id != first and not audio.playing and not app.player.revealed
    app.render()


def test_focus_drops_already_fetched_taps_and_finally_stops_audio(scene, monkeypatch):
    app, audio = scene
    click(app, app.word_rect.center)
    taps = [pygame.event.Event(kind, pos=app.word_rect.center, button=1, touch=False)
            for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP)]
    events = Mock(side_effect=[[pygame.event.Event(pygame.WINDOWFOCUSLOST), *taps], [pygame.event.Event(pygame.QUIT)]])
    monkeypatch.setattr(pygame.event, "get", events)
    app.run()
    assert len(audio.started) == 1 and not audio.playing and not app.player.revealed


def test_render_exception_releases_stream(scene, monkeypatch):
    app, audio = scene
    click(app, app.word_rect.center)
    monkeypatch.setattr(pygame.event, "get", lambda: [])
    monkeypatch.setattr(app, "render", Mock(side_effect=RuntimeError("failed render")))
    with pytest.raises(RuntimeError):
        app.run()
    assert not audio.playing and app.player.state == "stopped"


@pytest.mark.parametrize("size", [(800, 600), (1024, 600), (1024, 768), (1280, 800), (1366, 768)])
def test_six_launcher_icons_and_reading_controls_fit(scene, size):
    from toddlerbox.launcher import _build_buttons, _load_apps, _EMBEDDED_RUNNERS
    from toddlerbox.config import DEFAULT_CONFIG
    from toddlerbox.reading.app import ReadingApp
    old, _ = scene
    screen = pygame.display.set_mode(size)
    buttons = _build_buttons(_load_apps(DEFAULT_CONFIG), screen.get_rect())
    assert len(buttons) == 6 and "toddlerbox.reading" in _EMBEDDED_RUNNERS
    for i, button in enumerate(buttons):
        assert button.rect.w >= 120 and screen.get_rect().contains(button.rect)
        assert all(not button.rect.colliderect(other.rect) for other in buttons[i+1:])
    app = ReadingApp(screen, screen.get_rect(), pygame.time.Clock(), config=old.config, audio=Audio())
    controls = [app.word_rect, app.picture_rect, app.next_rect, app.home_rect]
    for i, rect in enumerate(controls):
        assert screen.get_rect().contains(rect)
        assert all(not rect.colliderect(other) for other in controls[i+1:])
    app.render()
    app.player.close()


def test_singleton_deck_and_empty_library_are_quiet(scene, tmp_path):
    from toddlerbox.reading.app import ReadingApp
    old, _ = scene
    catalog = json.loads((ASSETS / "catalog.json").read_text())
    card = catalog["cards"][0]
    for relative in [card["image"], card["sequence"]["path"], card["replay"]["path"]]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ASSETS / relative, path)
    catalog["cards"] = [card]
    (tmp_path / "catalog.json").write_text(json.dumps(catalog))
    app = ReadingApp(old.screen, old.rect, old.clock, config=old.config, audio=Audio(), library=tmp_path, previous_id=card["id"])
    assert app.card.id == card["id"] and not app.can_next
    app.player.revealed = True
    app.render()
    empty = ReadingApp(old.screen, old.rect, old.clock, config=old.config, audio=Audio(), library=tmp_path / "missing")
    empty.run()
    assert empty.card is None and empty.player.state == "stopped"


def test_visible_main_picture_replays_whole_word_once_per_deliberate_tap(scene):
    app, audio = scene
    pos = app.picture_rect.center
    assert not app.player.revealed and app._target(pos) is None
    click(app, pos)
    assert audio.started == []
    app.player.revealed = True
    assert app._target(pos) == "picture"
    click(app, pos)
    click(app, pos)
    assert audio.started == [app.card.replay.path.name]*2
    assert app.player.revealed
    for finger, mouse in [(pygame.FINGERDOWN, pygame.MOUSEBUTTONDOWN),
                          (pygame.FINGERUP, pygame.MOUSEBUTTONUP)]:
        app.handle_event(pygame.event.Event(finger, x=pos[0]/app.rect.w, y=pos[1]/app.rect.h,
                                           touch_id=1, finger_id=1))
        app.handle_event(pygame.event.Event(mouse, button=1, pos=pos, touch=True))
    assert len(audio.started) == 3
    app.next_card()
    assert not audio.playing and not app.player.revealed
