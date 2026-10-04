"""Bounded, independent sampled piano voices; never touch the song stream."""
from pathlib import Path
import pygame


class Piano:
    def __init__(self, keys, logger, *, library=None, volume=0.35):
        self.keys, self.logger = keys, logger
        self.library = library or Path(__file__).resolve().parents[3] / "assets/music/keys"
        self.volume = volume
        self.sounds = {}
        self.pointers = {}  # Up to eight raw fingers, or the real mouse.
        self.voices = {}
        self.channels = {}  # Retain fading channels until activity cleanup.

    def pitch_at(self, pos):
        for black in (True, False):
            for pitch, rect in self.keys.items():
                if (pitch % 12 in {1, 3, 6, 8, 10}) == black and rect.collidepoint(pos):
                    return pitch
        return None

    def _release(self, token):
        voice = self.voices.pop(token, None)
        if voice is not None:
            voice[1].fadeout(100)

    def _play(self, token, pitch):
        self._release(token)
        if pitch is None:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.set_num_channels(max(8, pygame.mixer.get_num_channels()))
            if pitch not in self.sounds:
                self.sounds[pitch] = pygame.mixer.Sound(str(self.library / f"{pitch}.wav"))
            occupied = {voice[0] for voice in self.voices.values()}
            slot = next((i for i in range(8) if i not in occupied), None)
            if slot is not None:
                voice = pygame.mixer.Channel(slot)
                self.channels[slot] = voice
                voice.set_volume(self.volume)
                voice.play(self.sounds[pitch])
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
            voice.stop()
        self.channels.clear()
        self.voices.clear()
        self.pointers.clear()
