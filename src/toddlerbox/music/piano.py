"""Bounded, independent sampled piano voices; never touch the song stream."""
from pathlib import Path
import time
import pygame


class Piano:
    def __init__(self, keys, logger, *, library=None, clock=time.monotonic):
        self.keys, self.logger = keys, logger
        self.library = library or Path(__file__).resolve().parents[3] / "assets/music/keys"
        # Key samples peak below 0.5. A shared 0.70 budget leaves room for
        # the song stream (peak <= 0.60), even with eight overlapping keys.
        self.volume = 0.70
        self.clock = clock
        self.sounds = {}
        self.sustains = {}
        self.pointers = {}  # Up to eight raw fingers, or the real mouse.
        self.voices = {}
        self.channels = {}  # Retain fading channels until activity cleanup.
        self.tails = {}  # Insertion order makes the oldest release stealable first.
        self.gains = {}
        self.slot_sustains = {}
        self.prepare()

    def prepare(self):
        """Load the fixed 25-key bank silently on the UI thread before input.

        Fifty small, shipped WAVs are the entire preparation budget. Publish
        each attack/loop pair together; an unavailable key never performs file
        IO on a touch. Calling this explicitly retries unavailable pairs.
        """
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.set_num_channels(max(8, pygame.mixer.get_num_channels()))
        except pygame.error:
            self.logger.exception("Piano preparation unavailable")
            return False
        for pitch in range(48, 73):
            if pitch in self.sounds:
                continue
            try:
                attack = pygame.mixer.Sound(str(self.library / "sustain" / f"{pitch}-attack.wav"))
                sustain = pygame.mixer.Sound(str(self.library / "sustain" / f"{pitch}-loop.wav"))
            except (pygame.error, OSError):
                self.logger.exception("Piano sound unavailable")
                continue
            self.sounds[pitch], self.sustains[pitch] = attack, sustain
        return len(self.sounds) == 25

    @staticmethod
    def _stop_channel(voice):
        # SDL's finished callback can start the single queued Sound on stop.
        # Mute first, halt it, then halt that queued successor as well. There
        # is never more than one successor and only this thread enqueues it.
        voice.set_volume(0)
        voice.stop()
        voice.stop()

    def update(self):
        now = self.clock()
        held = {voice[0] for voice in self.voices.values()}
        for slot in held | set(self.tails):
            voice = self.channels[slot]
            gain = self.gains[slot]
            if slot in self.tails:
                released, gain = self.tails[slot]
                remaining = 1 - (now - released) / .6
                if remaining <= 0:
                    self._stop_channel(voice)
                    del self.tails[slot]
                    continue
                gain *= remaining * remaining
            # A delayed frame can exhaust the queued loop. Apply the effective
            # envelope BEFORE restart; a released note must never swell again.
            voice.set_volume(gain)
            # Keep at most one short loop queued. It sustains a healthy held
            # note without replaying its attack or interrupting the song.
            if not voice.get_busy():
                voice.play(self.slot_sustains[slot])
            if voice.get_queue() is None:
                voice.queue(self.slot_sustains[slot])

    def _reserve_gain(self):
        self.update()
        owned = {voice[0] for voice in self.voices.values()} | set(self.tails)
        busy = [slot for slot, voice in self.channels.items() if slot in owned or voice.get_busy()]
        gain = self.volume / (len(busy) + 1)
        for slot in busy:
            # Never swell an existing voice as other keys finish their decay.
            self.gains[slot] = min(self.gains[slot], gain)
            if slot in self.tails:
                released, previous = self.tails[slot]
                self.tails[slot] = (released, min(previous, gain))
            else:
                self.channels[slot].set_volume(self.gains[slot])
        self.update()
        return gain

    def pitch_at(self, pos):
        for black in (True, False):
            for pitch, rect in self.keys.items():
                if (pitch % 12 in {1, 3, 6, 8, 10}) == black and rect.collidepoint(pos):
                    return pitch
        return None

    def _release(self, token):
        self.update()
        voice = self.voices.pop(token, None)
        if voice is not None:
            # SDL fadeout rewrites channel volume and can undo headroom limits.
            # Own the short envelope in the normal event loop instead.
            self.tails[voice[0]] = (self.clock(), self.gains[voice[0]])

    def _play(self, token, pitch):
        self._release(token)
        if pitch is None or pitch not in self.sounds:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.set_num_channels(max(8, pygame.mixer.get_num_channels()))
            occupied = {voice[0] for voice in self.voices.values()}
            self.update()
            slot = next((i for i in range(8) if i not in occupied
                         and (i not in self.channels or not self.channels[i].get_busy())), None)
            if slot is None:
                slot = next((i for i in self.tails if i not in occupied), None)
            if slot is not None:
                self.tails.pop(slot, None)
                voice = pygame.mixer.Channel(slot)
                self._stop_channel(voice)
                gain = self._reserve_gain()
                self.channels[slot] = voice
                self.gains[slot] = gain
                self.slot_sustains[slot] = self.sustains[pitch]
                voice.set_volume(gain)
                voice.play(self.sounds[pitch])
                voice.queue(self.sustains[pitch])
                self.voices[token] = (slot, voice)
        except (pygame.error, OSError):
            self.logger.exception("Piano sound unavailable")

    @property
    def active(self):
        return {pitch for pitch in self.pointers.values() if pitch is not None}

    def event(self, event, screen_rect):
        from toddlerbox.ui.common import pointer_event_pos
        if event.type in {pygame.FINGERDOWN, pygame.FINGERUP, pygame.FINGERMOTION}:
            token = ("finger", getattr(event, "touch_id", 0), getattr(event, "finger_id", 0))
            down, up = event.type == pygame.FINGERDOWN, event.type == pygame.FINGERUP
        elif event.type in {pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION}:
            if getattr(event, "touch", False):
                return False  # The shared pointer gate discards SDL touch emulation.
            if event.type != pygame.MOUSEMOTION and getattr(event, "button", 1) != 1:
                return False
            token = ("mouse",)
            down, up = event.type == pygame.MOUSEBUTTONDOWN, event.type == pygame.MOUSEBUTTONUP
        else:
            return False
        pos = pointer_event_pos(event, screen_rect)
        pitch = self.pitch_at(pos) if pos is not None else None
        if down:
            if pitch is None:
                return False
            if token in self.pointers or len(self.pointers) >= 8:
                return True
            self.pointers[token] = pitch
            self._play(token, pitch)
            return True
        if token not in self.pointers:
            return False
        if up:
            self._release(token)
            del self.pointers[token]
        elif pitch != self.pointers[token]:
            self.pointers[token] = pitch
            self._play(token, pitch)
        return True

    def close(self):
        for voice in self.channels.values():
            self._stop_channel(voice)
        self.channels.clear()
        self.tails.clear()
        self.gains.clear()
        self.slot_sustains.clear()
        self.voices.clear()
        self.pointers.clear()
