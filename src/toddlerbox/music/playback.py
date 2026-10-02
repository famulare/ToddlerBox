from __future__ import annotations

import time
import math
from typing import Callable

import pygame

from toddlerbox.music.library import Track


class SDLAudio:
    """The process owns the mixer; this activity owns its music stream."""

    def play(self, track: Track, volume: float) -> None:
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        pygame.mixer.music.set_endevent()  # Completion is polled, never event-driven.
        pygame.mixer.music.load(str(track.audio))
        pygame.mixer.music.set_volume(volume)
        pygame.mixer.music.play()

    def position(self) -> int:
        return pygame.mixer.music.get_pos()

    def busy(self) -> bool:
        return pygame.mixer.music.get_busy()

    def pause(self) -> None:
        pygame.mixer.music.pause()

    def resume(self) -> None:
        pygame.mixer.music.unpause()

    def stop(self) -> None:
        if pygame.mixer.get_init():
            pygame.mixer.music.set_endevent()
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()


class MusicPlayer:
    """Bounded playlist and one audio-derived clock, independent of rendering."""

    def __init__(self, tracks: list[Track], logger, *, audio=None,
                 volume: float = 0.25, autoplay: bool = True,
                 latency_ms: float = 0, clock: Callable[[], float] = time.monotonic):
        self.tracks = tracks
        self.logger = logger
        self.audio = audio if audio is not None else SDLAudio()
        def setting(value, default, low, high, name):
            try:
                number = float(value)
                if isinstance(value, bool) or not math.isfinite(number):
                    raise ValueError("non-finite or boolean setting")
            except (ValueError, TypeError, OverflowError):
                logger.info(f"Invalid Music {name}; using default")
                return default
            return max(low, min(high, number))
        self.volume = setting(volume, 0.25, 0.0, 1.0, "volume")
        self.latency_ms = setting(latency_ms, 0.0, -500.0, 500.0, "latency")
        self.autoplay = autoplay
        self.clock = clock
        self.index = 0
        self.state = "stopped"
        self.failed: set[int] = set()
        self._position = 0.0
        self._offset = 0.0
        self._gap_until = 0.0
        self._gap_remaining = 0.0
        self._paused_from = "playing"

    @property
    def track(self) -> Track | None:
        return self.tracks[self.index] if self.tracks else None

    @property
    def position_ms(self) -> float:
        if self.track is None:
            return 0.0
        return max(0.0, min(self.track.duration_ms, self._position - self.latency_ms))

    def _stop_audio(self) -> None:
        try:
            self.audio.stop()
        except (pygame.error, OSError):
            self.logger.exception("Music audio cleanup failed")

    def select(self, index: int, *, manual: bool = True) -> None:
        if not self.tracks:
            self.state = "unavailable"
            return
        self._stop_audio()
        if manual:
            self.failed.clear()
        self.index = index % len(self.tracks)
        self._position = self._offset = 0.0
        try:
            self.audio.play(self.track, self.volume)
        except (pygame.error, OSError):
            self.logger.exception(f"Music playback unavailable: {self.track.id}")
            self._stop_audio()
            self.failed.add(self.index)
            self.state = "unavailable"
            if self.autoplay and len(self.failed) < len(self.tracks):
                self.state = "gap"
                self._gap_until = self.clock() + 0.6
            return
        self.state = "playing"

    def _read_position(self) -> None:
        raw = self.audio.position()
        if raw >= 0:
            self._position = min(self.track.duration_ms, max(self._position, raw + self._offset))

    def toggle_pause(self) -> None:
        try:
            if self.state == "playing":
                self._read_position()
                self.audio.pause()
                self._paused_from = "playing"
                self.state = "paused"
            elif self.state == "gap":
                self._gap_remaining = max(0.0, self._gap_until - self.clock())
                self._paused_from = "gap"
                self.state = "paused"
            elif self.state == "paused":
                if self._paused_from == "gap":
                    self._gap_until = self.clock() + self._gap_remaining
                    self.state = "gap"
                else:
                    self.audio.resume()
                    raw = self.audio.position()
                    if raw >= 0:
                        self._offset = self._position - raw
                    self.state = "playing"
            else:
                self.select(self.index)
        except (pygame.error, OSError):
            self.logger.exception("Music pause/resume failed")
            self._stop_audio()
            self.state = "unavailable"

    def toggle_autoplay(self) -> None:
        self.autoplay = not self.autoplay
        if not self.autoplay and (self.state == "gap" or
                                 (self.state == "paused" and self._paused_from == "gap")):
            self.state = "finished"

    def update(self) -> None:
        if self.state == "gap":
            if self.clock() >= self._gap_until:
                for step in range(1, len(self.tracks) + 1):
                    candidate = (self.index + step) % len(self.tracks)
                    if candidate not in self.failed:
                        self.select(candidate, manual=False)
                        break
                else:
                    self.state = "unavailable"
            return
        if self.state != "playing":
            return
        try:
            self._read_position()
            if self.audio.busy():
                return
        except (pygame.error, OSError):
            self.logger.exception("Music device became unavailable")
            self._stop_audio()
            self.state = "unavailable"
            return
        # A very early stream stop indicates device/decoder failure, not a finished song.
        if self.track and self._position < self.track.duration_ms - 1000:
            self.failed.add(self.index)
            self.logger.info(f"Music stream ended early: {self.track.id}")
        else:
            self._position = self.track.duration_ms if self.track else 0
        self._stop_audio()
        self.state = "finished"
        if self.autoplay and len(self.failed) < len(self.tracks):
            self.state = "gap"
            self._gap_until = self.clock() + 0.6

    def close(self) -> None:
        self.state = "stopped"
        self._stop_audio()
