"""Bounded, offline number clips. Playback never changes question state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
import wave

import pygame

from toddlerbox.reading.catalog import RATE, Speech
from toddlerbox.reading.playback import SDLSpeech, SpeechAssetError, SpeechDeviceError

ROOT = Path(__file__).resolve().parents[3] / "assets/math/audio"


class NumberBank:
    def __init__(self, logger, root=ROOT):
        self.logger, self.root = logger, Path(root).resolve()
        self.entries, self.operators, self.cache = {}, {}, {}
        try:
            path = self.root / "catalog.json"
            if path.is_symlink() or not 0 < path.stat().st_size <= 100_000:
                raise ValueError("Invalid number catalog")
            catalog = json.loads(path.read_text())
            if type(catalog["schema_version"]) is not int or catalog["schema_version"] != 1 or catalog["sample_rate"] != RATE:
                raise ValueError("Unsupported number catalog")
            rows = catalog["clips"]
            if not isinstance(rows, list) or len(rows) > 101:
                raise ValueError("Invalid number collection")
            for row in rows:
                number = row["number"]
                if type(number) is not int or not 0 <= number <= 100 or number in self.entries:
                    raise ValueError("Invalid or duplicate number")
                self.entries[number] = row
            operators = catalog.get("operators", [])
            if not isinstance(operators, list) or len(operators) > 3:
                raise ValueError("Invalid equation words")
            for row in operators:
                name = row["id"]
                if name not in ("plus", "minus", "equals") or name in self.operators:
                    raise ValueError("Invalid equation word")
                self.operators[name] = row
        except (OSError, ValueError, TypeError, KeyError):
            self.entries.clear()
            self.operators.clear()
            logger.exception("Math number recordings unavailable")

    def get(self, number):
        if type(number) is not int or number not in self.entries:
            return None
        return self._get(number, self.entries[number], f"number-{number}.wav")

    def operator(self, name):
        if type(name) is not str or name not in self.operators:
            return None
        return self._get(name, self.operators[name], f"{name}.wav")

    def _get(self, key, row, filename):
        if key in self.cache:
            return self.cache[key]
        clip = None
        try:
            # Generated only from a bounded integer or three fixed operator IDs.
            path = self.root / filename
            if path.is_symlink() or not path.is_file() or not 44 <= path.stat().st_size <= 600_000:
                raise ValueError("Invalid number recording")
            frames = row["frames"]
            if type(frames) is not int or not 1000 <= frames <= RATE * 6:
                raise ValueError("Invalid recording duration")
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError("Changed number recording")
            with wave.open(str(path), "rb") as source:
                if (source.getframerate(), source.getnchannels(), source.getsampwidth(), source.getnframes(), source.getcomptype()) != (RATE, 1, 2, frames, "NONE"):
                    raise ValueError("Unsupported number recording")
                if len(source.readframes(frames)) != frames * 2:
                    raise ValueError("Truncated number recording")
            clip = Speech(path, frames, ())
        except (OSError, ValueError, TypeError, KeyError, wave.Error, EOFError):
            self.logger.exception("Skipping damaged Math recording")
        self.cache[key] = clip
        return clip


class NumberPlayer:
    def __init__(self, logger, *, volume=0.70, bank=None, audio=None, clock=time.monotonic):
        self.logger, self.volume, self.clock = logger, volume, clock
        self.bank = NumberBank(logger) if bank is None else bank
        self.audio = SDLSpeech() if audio is None else audio
        self.deadline = None
        self.queue = []

    def cancel(self):
        self.deadline = None
        self.queue.clear()
        try:
            self.audio.stop()
        except (pygame.error, OSError):
            self.logger.exception("Math sound cleanup failed")

    def play(self, number):
        self.cancel()
        clip = self.bank.get(number)
        if clip is None:
            return
        self._start(clip)

    def play_equation(self, example):
        self.cancel()
        from toddlerbox.math.model import Example
        if not isinstance(example, Example) or example.mode not in ("addition", "subtraction"):
            return
        clips = [self.bank.get(example.a),
                 self.bank.operator("plus" if example.mode == "addition" else "minus"),
                 self.bank.get(example.b), self.bank.operator("equals"),
                 self.bank.get(example.result)]
        # A damaged word must not turn an equation into misleading partial speech.
        if any(clip is None for clip in clips):
            return
        self.queue = clips[1:]
        self._start(clips[0])

    def _start(self, clip):
        try:
            self.audio.play(clip, self.volume)
            self.started = self.clock()
            self.duration = clip.duration_ms / 1000
            self.deadline = self.started + self.duration + 1
        except (SpeechAssetError, SpeechDeviceError, pygame.error, OSError):
            self.logger.exception("Math sound unavailable")
            self.cancel()  # Device failure can be retried on the next deliberate tap.

    def update(self):
        if self.deadline is None:
            return
        try:
            if self.clock() >= self.deadline:
                self.cancel()
            elif not self.audio.busy():
                if self.clock() - self.started < self.duration - .05:
                    self.cancel()  # Do not skip a word after a prematurely stopped stream.
                elif self.queue:
                    self._start(self.queue.pop(0))
                else:
                    self.cancel()
        except (pygame.error, OSError):
            self.logger.exception("Math sound device stopped")
            self.cancel()
