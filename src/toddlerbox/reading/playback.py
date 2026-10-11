from __future__ import annotations

import time
import io
import wave

import pygame

from toddlerbox.reading.catalog import Card, RATE, Speech


class SpeechAssetError(Exception):
    pass


class SpeechDeviceError(Exception):
    pass


class SDLSpeech:
    """One activity-owned stream; the application owns SDL's mixer."""

    def play(self, speech: Speech, volume: float) -> None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=RATE, size=-16, channels=2, buffer=512)
            pygame.mixer.music.set_endevent()
        except pygame.error as exc:
            raise SpeechDeviceError from exc
        try:
            self._clip = None
            if speech.start_frame or (len(speech.cues) == 1 and speech.cues[0].unit >= 0):
                with wave.open(str(speech.path), "rb") as source:
                    source.setpos(speech.start_frame)
                    data = source.readframes(speech.frames)
                    if len(data) != speech.frames * 2:
                        raise OSError("Truncated sound unit")
                self._clip = io.BytesIO()
                with wave.open(self._clip, "wb") as target:
                    target.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
                    target.writeframes(data)
                self._clip.seek(0)
                pygame.mixer.music.load(self._clip, "wav")
            else:
                pygame.mixer.music.load(str(speech.path))
        except (pygame.error, OSError, wave.Error, EOFError) as exc:
            raise SpeechAssetError from exc
        try:
            pygame.mixer.music.set_volume(volume)
            pygame.mixer.music.play()
        except pygame.error as exc:
            raise SpeechDeviceError from exc

    def position(self) -> int:
        return pygame.mixer.music.get_pos()

    def busy(self) -> bool:
        return pygame.mixer.music.get_busy()

    def stop(self) -> None:
        if pygame.mixer.get_init():
            pygame.mixer.music.set_endevent()
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()


class SpeechPlayer:
    def __init__(self, logger, *, audio=None, volume=0.70, clock=time.monotonic):
        self.logger = logger
        self.audio = SDLSpeech() if audio is None else audio
        self.volume, self.clock = volume, clock
        self.card: Card | None = None
        self.speech: Speech | None = None
        self.state = "idle"
        self.revealed = False
        self.failed: set[str] = set()
        self.position_ms = 0.0
        self._started = 0.0
        self._reveal_when_finished = True

    def _stop(self) -> None:
        try:
            self.audio.stop()
        except (pygame.error, OSError):
            self.logger.exception("Reading audio cleanup failed")

    def cancel(self) -> None:
        self._stop()
        self.state = "revealed" if self.revealed else "idle"
        self.speech = None
        self.position_ms = 0

    def select(self, card: Card) -> None:
        self.cancel()
        self.card, self.revealed, self.state = card, False, "idle"

    def play(self, *, whole_word=False) -> None:
        if self.card is None or self.card.id in self.failed or self.state == "playing":
            return
        self._stop()
        self.speech = self.card.replay if whole_word else self.card.sequence
        self._reveal_when_finished = True
        self.position_ms = 0
        try:
            self.audio.play(self.speech, self.volume)
        except SpeechAssetError:
            self.failed.add(self.card.id)
            self.logger.exception("Reading recording unavailable")
            self._unavailable()
            return
        except (SpeechDeviceError, pygame.error, OSError):
            self.logger.exception("Reading sound device unavailable")
            self._unavailable()
            return
        self._started = self.clock()
        self.state = "playing"

    def play_unit(self, index: int) -> None:
        """One sound per tap, interrupting the previous sound without queuing."""
        if self.card is None or self.card.id in self.failed or type(index) is not int or not 0 <= index < len(self.card.units):
            return
        cue = next((cue for cue in self.card.sequence.cues if cue.unit == index), None)
        if cue is None and self.card.kind == "letters":
            self.cancel()
            self.play(whole_word=True)
            self._reveal_when_finished = False
            return
        if cue is None:
            self.logger.info("Reading card is missing this sound unit")
            return
        self.cancel()
        from toddlerbox.reading.catalog import Cue
        self.speech = Speech(self.card.sequence.path, cue.end - cue.start,
                             (Cue(0, cue.end - cue.start, index),), cue.start)
        self._reveal_when_finished = False
        try:
            self.audio.play(self.speech, self.volume)
        except SpeechAssetError:
            self.failed.add(self.card.id)
            self._unavailable()
            self.logger.exception("Reading sound unavailable")
            return
        except (SpeechDeviceError, pygame.error, OSError):
            self._unavailable()
            self.logger.exception("Reading sound device unavailable")
            return
        self._started = self.clock()
        self.state = "playing"

    def _unavailable(self) -> None:
        self._stop()
        self.state = "unavailable"
        self.speech = None
        self.position_ms = 0

    @property
    def active_unit(self) -> int | None:
        if self.state != "playing" or self.speech is None:
            return None
        frame = self.position_ms * RATE / 1000
        return next((cue.unit for cue in self.speech.cues if cue.start <= frame < cue.end), None)

    def update(self) -> None:
        if self.state != "playing":
            return
        try:
            raw = self.audio.position()
            if raw >= 0:
                self.position_ms = min(self.speech.duration_ms, max(self.position_ms, raw))
            if self.audio.busy():
                if (self.clock() - self._started) * 1000 > self.speech.duration_ms + 1000:
                    self.logger.info("Reading sound stream exceeded its duration")
                    self._unavailable()
                return
        except (pygame.error, OSError):
            self.logger.exception("Reading sound device stopped")
            self._unavailable()
            return
        elapsed = (self.clock() - self._started) * 1000
        # SDL may return -1 just after the last buffer. Allow one short polling
        # interval, not a stream that never played or stopped much too early.
        finished = self.position_ms > 0 and (
            self.position_ms >= self.speech.duration_ms - 100 or
            elapsed >= self.speech.duration_ms - 50)
        self._stop()
        if not finished:
            self.logger.info("Reading recording stopped early")
            self.state = "unavailable"
            self.speech = None
            self.position_ms = 0
            return
        self.revealed = self.revealed or self._reveal_when_finished
        self.state = "revealed" if self.revealed else "idle"
        self.speech = None
        self.position_ms = 0

    def close(self) -> None:
        self.cancel()
        self.state = "stopped"
