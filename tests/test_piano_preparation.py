"""Preparation removes asset decoding from touch without starting any audio."""
import threading
from unittest.mock import Mock

import pygame
import pytest

from toddlerbox.music.piano import Piano


@pytest.fixture
def mixer(monkeypatch):
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    yield
    pygame.mixer.music.stop()
    pygame.mixer.quit()


def test_fixed_bank_prepares_on_caller_thread_without_playing_and_touch_needs_no_io(mixer, monkeypatch):
    original = pygame.mixer.Sound
    caller = threading.get_ident()
    paths = []
    def load(path):
        assert threading.get_ident() == caller
        paths.append(path)
        return original(path)
    monkeypatch.setattr(pygame.mixer, "Sound", load)
    piano = Piano({60: pygame.Rect(0, 0, 100, 100)}, Mock())
    try:
        assert len(paths) == 50
        assert set(piano.sounds) == set(piano.sustains) == set(range(48, 73))
        assert not piano.voices and not piano.channels and not pygame.mixer.get_busy()
        monkeypatch.setattr(pygame.mixer, "Sound", Mock(side_effect=AssertionError("Asset IO on touch")))
        piano.event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(50, 50), button=1),
                    pygame.Rect(0, 0, 100, 100))
        assert piano.active == {60} and piano.voices
        for pitch in range(48, 73):
            piano._play("sweep", pitch)
        assert len(piano.channels) <= 8
        assert piano.prepare()  # Already prepared; no decoding or note replay.
    finally:
        piano.close()
    assert not pygame.mixer.get_busy()


def test_missing_pair_is_quarantined_until_explicit_silent_retry(mixer, monkeypatch):
    original = pygame.mixer.Sound
    def load(path):
        if path.endswith("60-loop.wav"):
            raise pygame.error("Missing fixture loop")
        return original(path)
    monkeypatch.setattr(pygame.mixer, "Sound", load)
    piano = Piano({}, Mock())
    try:
        assert len(piano.sounds) == 24 and 60 not in piano.sounds and 60 not in piano.sustains
        no_io = Mock(side_effect=AssertionError("Retry IO on touch"))
        monkeypatch.setattr(pygame.mixer, "Sound", no_io)
        piano._play("bad", 60)
        piano._play("bad", 60)
        no_io.assert_not_called()
        assert not piano.voices
        piano._play("good", 64)
        slot, channel = piano.voices["good"]
        loader = Mock(side_effect=original)
        monkeypatch.setattr(pygame.mixer, "Sound", loader)
        assert piano.prepare()
        assert loader.call_count == 2 and piano.voices["good"][0] == slot and channel.get_busy()
    finally:
        piano.close()


def test_unavailable_mixer_during_preparation_fails_quietly_without_touch_retry(mixer, monkeypatch):
    monkeypatch.setattr(pygame.mixer, "get_init", lambda: None)
    initialize = Mock(side_effect=pygame.error("Device unavailable"))
    monkeypatch.setattr(pygame.mixer, "init", initialize)
    piano = Piano({}, Mock())
    piano._play("key", 60)
    assert initialize.call_count == 1
    assert not piano.sounds and not piano.sustains and not piano.voices


def test_preparation_preserves_existing_song_stream(mixer):
    from pathlib import Path
    song = Path(__file__).parents[1] / "assets/music/mary.wav"
    pygame.mixer.music.load(str(song))
    pygame.mixer.music.play()
    piano = Piano({}, Mock())
    try:
        assert pygame.mixer.music.get_busy()
        assert not piano.voices and not pygame.mixer.get_busy()
        piano.close()
        assert pygame.mixer.music.get_busy()
    finally:
        piano.close()
