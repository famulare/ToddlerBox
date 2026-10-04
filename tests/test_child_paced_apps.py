"""Actual PCM/channel and rendered/input observables for the HP feature requests."""
import hashlib
import io
import json
from pathlib import Path
import random
from unittest.mock import Mock
import wave

import pygame
import pytest

from toddlerbox.reading.catalog import Options, load_catalog
from toddlerbox.reading.playback import SDLSpeech, SpeechPlayer

ROOT = Path(__file__).parents[1]


@pytest.fixture
def display(tmp_path, monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    screen = pygame.display.set_mode((1366, 768))
    yield screen, {"data_root": str(tmp_path)}
    pygame.mixer.music.stop()
    pygame.quit()


def tap(app, pos):
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        app.handle_event(pygame.event.Event(kind, pos=pos, button=1, touch=False))


class SpeechAudio:
    def __init__(self):
        self.speech = None
        self.pos = 0
        self.playing = False
        self.history = []
    def play(self, speech, volume):
        self.speech = speech
        self.history.append(speech)
        self.pos, self.playing = 0, True
    def position(self):
        return self.pos
    def busy(self):
        return self.playing
    def stop(self):
        self.playing = False


def reading(display):
    from toddlerbox.reading.app import ReadingApp
    screen, config = display
    audio = SpeechAudio()
    app = ReadingApp(screen, screen.get_rect(), pygame.time.Clock(), config=config,
                     audio=audio, rng=random.Random(3))
    app.select_card(next(card for card in app.cards if card.text == "cat"))
    return app, audio


def pixels(screen, rect):
    return pygame.image.tobytes(screen.subsurface(rect), "RGBA")


def test_sound_taps_never_autoplay_other_units_or_reveal_picture(display):
    app, audio = reading(display)
    assert not audio.history
    tap(app, app._unit_rects[0].center)
    first = audio.speech
    tap(app, app._unit_rects[2].center)
    assert [speech.cues[0].unit for speech in audio.history] == [0, 2]
    assert first.frames < app.card.sequence.frames
    audio.pos = audio.speech.duration_ms
    audio.playing = False
    app.player.update()
    assert app.player.state == "idle" and not app.player.revealed
    assert len(audio.history) == 2
    tap(app, app.read_rect.center)
    assert audio.speech == app.card.replay
    audio.pos, audio.playing = audio.speech.duration_ms, False
    app.player.update()
    assert app.player.revealed


def test_actual_sdl_sound_slice_matches_source_pcm_exactly(display, monkeypatch):
    app, audio = reading(display)
    for index in range(len(app.card.units)):
        app.player.play_unit(index)
        speech = audio.speech
        captured = []
        def load(source, hint=None):
            captured.append(source.getvalue())
        monkeypatch.setattr(pygame.mixer.music, "load", load)
        monkeypatch.setattr(pygame.mixer.music, "play", lambda: None)
        SDLSpeech().play(speech, 0.35)
        with wave.open(io.BytesIO(captured[0])) as decoded, wave.open(str(app.card.sequence.path)) as original:
            cue = next(cue for cue in app.card.sequence.cues if cue.unit == index)
            original.setpos(cue.start)
            assert decoded.getnframes() == cue.end - cue.start
            assert decoded.readframes(decoded.getnframes()) == original.readframes(cue.end - cue.start)


def test_letter_sound_waits_for_deliberate_name_button_to_reveal(display):
    audio = SpeechAudio()
    player = SpeechPlayer(Mock(), audio=audio)
    card = load_catalog(ROOT / "assets/reading", Options(mode="letters"), Mock())[0]
    player.select(card)
    player.play_unit(0)
    audio.pos, audio.playing = audio.speech.duration_ms, False
    player.update()
    assert not player.revealed and player.state == "idle"
    player.play(whole_word=True)
    audio.pos, audio.playing = audio.speech.duration_ms, False
    player.update()
    assert player.revealed


def test_rail_toggle_changes_actual_preview_pixels_without_revealing_main_picture(display):
    app, _ = reading(display)
    app.render()
    rail_before = pixels(app.screen, app.rail)
    picture_before = pixels(app.screen, app.picture_rect)
    tap(app, app.images_toggle.center)
    app.render()
    assert pixels(app.screen, app.rail) != rail_before
    assert pixels(app.screen, app.picture_rect) == picture_before
    first, row = next(app._rail_rows())
    tap(app, row.center)
    assert app.card.id == first.id and not app.player.revealed
    tap(app, app.words_toggle.center)
    assert not app.rail_images


def test_rail_scroll_is_bounded_and_does_not_select_on_drag(display):
    app, _ = reading(display)
    current = app.card.id
    x, y = app.rail.center
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(x,y), button=1))
    app.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(x,y-150), buttons=(1,0,0)))
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(x,y-150), button=1))
    assert app.card.id == current and app.rail_offset == 150
    app._scroll(999999)
    assert app.rail_offset == len(app.cards)*76 - app.rail.h


def test_expanded_words_are_harder_and_numbers_are_absent():
    cards = load_catalog(ROOT / "assets/reading", Options(), Mock())
    assert len(cards) == 75
    assert len({card.text for card in cards}) == 75
    assert any(len(card.text) >= 5 for card in cards)
    assert {tag for card in cards for tag in card.tags} == set(Options().word_sets)
    assert options_legacy_numbers().mode == "words"
    assert not list((ROOT / "assets/reading/audio").glob("number-*.wav"))
    egg = next(card for card in cards if card.text == "egg")
    assert egg.units == ("e", "gg")
    assert [cue.unit for cue in egg.sequence.cues if cue.unit >= 0] == [0, 1]


def options_legacy_numbers():
    from toddlerbox.reading.catalog import options_from_config
    return options_from_config({"reading": {"mode":"numbers", "number_max":30}}, Mock())


def test_piano_notes_use_independent_voices_and_leave_real_song_running(display):
    from toddlerbox.music.app import MusicApp
    screen, config = display
    app = MusicApp(screen, screen.get_rect(), pygame.time.Clock(), config=config)
    app.player.select(0)
    assert pygame.mixer.music.get_busy()
    stream_position = pygame.mixer.music.get_pos()
    for finger, pitch in enumerate((60,64,67)):
        x,y = app.keys[pitch].center
        app.handle_event(pygame.event.Event(pygame.FINGERDOWN, x=x/screen.get_width(),
                         y=y/screen.get_height(), finger_id=finger, touch_id=1))
    assert app.piano.active == {60,64,67}
    assert len({slot for slot, voice in app.piano.voices.values()}) == 3
    assert all(voice.get_busy() for slot, voice in app.piano.voices.values())
    assert pygame.mixer.music.get_busy() and pygame.mixer.music.get_pos() >= stream_position
    assert app.player.state == "playing" and app.player.index == 0
    app.piano.close()
    app.player.close()


def test_piano_black_key_priority_emulation_glissando_focus_and_free_play(display):
    from toddlerbox.music.app import MusicApp
    screen, config = display
    app = MusicApp(screen, screen.get_rect(), pygame.time.Clock(), config=config)
    app.player.select(0)
    black = app.keys[61].center
    tap(app, black)  # Release ends the played voice.
    assert not app.piano.active
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=black, button=1))
    assert app.piano.active == {61}
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=app.keys[64].center, button=1, touch=True))
    assert app.piano.active == {61}
    app.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=app.keys[64].center, buttons=(1,0,0)))
    assert app.piano.active == {64}
    app.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
    assert not app.piano.active and not app.piano.voices
    tap(app, app.free_rect.center)
    assert app.free_play and not pygame.mixer.music.get_busy()
    before = pixels(screen, app.keyboard_rect)
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=app.keys[60].center, button=1))
    app.render()
    assert app.piano.active == {60} and pixels(screen, app.keyboard_rect) != before
    assert not pygame.mixer.music.get_busy()
    app.piano.close()


def test_all_25_piano_keys_are_non_silent_bounded_verified_pcm():
    root = ROOT / "assets/music/keys"
    manifest = json.loads((root / "manifest.json").read_text())
    assert set(manifest["sha256"]) == {f"{pitch}.wav" for pitch in range(48,73)}
    for filename, digest in manifest["sha256"].items():
        path = root / filename
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        with wave.open(str(path)) as source:
            assert (source.getnchannels(),source.getsampwidth(),source.getframerate(),source.getnframes()) == (1,2,22050,44100)
            raw = source.readframes(source.getnframes())
        assert any(raw)


def test_piano_cleanup_stops_released_fading_notes(display):
    from toddlerbox.music.app import MusicApp
    screen, config = display
    app = MusicApp(screen, screen.get_rect(), pygame.time.Clock(), config=config)
    pos = app.keys[60].center
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
    channel = next(iter(app.piano.voices.values()))[1]
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1))
    assert not app.piano.voices
    app.piano.close()
    assert not channel.get_busy()
