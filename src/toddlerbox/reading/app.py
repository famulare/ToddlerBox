from __future__ import annotations

import os
from pathlib import Path
import random
import time

import pygame

from toddlerbox.config import load_config
from toddlerbox.paths import get_data_root
from toddlerbox.reading.catalog import load_catalog, options_from_config
from toddlerbox.reading.playback import SpeechPlayer
from toddlerbox.reading.selection import choose_next
from toddlerbox.runtime import get_runtime_logger, health, control
from toddlerbox.ui import theme
from toddlerbox.ui.common import (PointerInput, create_fullscreen_window, draw_home_button,
                                  is_escape_chord, is_primary_pointer_event, pointer_event_pos)

FOCUS_EVENTS = {getattr(pygame, "WINDOWFOCUSLOST", -1),
                getattr(pygame, "WINDOWFOCUSGAINED", -2),
                getattr(pygame, "APP_DIDENTERFOREGROUND", -3),
                getattr(pygame, "APP_WILLENTERBACKGROUND", -4)}
_last_card_id: str | None = None  # Only the current process; never learning history.


class ReadingApp:
    def __init__(self, screen, screen_rect, clock, *, config=None, audio=None,
                 rng=None, library=None, previous_id=None):
        self.screen, self.rect, self.clock = screen, screen_rect, clock
        self.config = load_config() if config is None else config
        self.logger = get_runtime_logger(get_data_root(self.config))
        self.options = options_from_config(self.config, self.logger)
        root = library or Path(__file__).resolve().parents[3] / "assets/reading"
        self.cards = load_catalog(root, self.options, self.logger)
        self.rng = random.Random() if rng is None else rng
        self.player = SpeechPlayer(self.logger, audio=audio, volume=self.options.volume)
        self.pointer = PointerInput()
        self.pressed = None
        self.bad_images: set[str] = set()
        self.card = None
        self.picture = None
        self.home_rect = theme.home_rect(self.rect)
        margin = max(16, min(32, self.rect.w // 32))
        arrow_width = 80
        self.panel = pygame.Rect(margin, 100, self.rect.w - margin * 3 - arrow_width,
                                 self.rect.h - 100 - margin)
        self.next_rect = pygame.Rect(self.panel.right + margin, self.panel.centery - 40, arrow_width, 80)
        self.word_rect = pygame.Rect(self.panel.x + 16, self.panel.y + 16, self.panel.w - 32,
                                     max(120, min(180, self.panel.h // 3)))
        self.picture_rect = pygame.Rect(self.panel.x + 20, self.word_rect.bottom + 12,
                                        self.panel.w - 40, self.panel.bottom - self.word_rect.bottom - 32)
        self.arrow = theme.arrow("right", (60, 72))
        self.title = theme.ui_font(28, bold=True).render("Reading", True, theme.INK)
        self._unit_rects = []
        self._unit_text = []
        self._unit_highlight = []
        self.next_card(previous_id=previous_id)

    def _available(self):
        excluded = self.player.failed | self.bad_images
        return [card for card in self.cards if card.id not in excluded]

    @property
    def can_next(self):
        return any(card.id != (self.card.id if self.card else None) for card in self._available())

    def next_card(self, *, previous_id=None) -> bool:
        self.player.cancel()
        current_id = self.card.id if self.card else previous_id
        available = self._available()
        # A singleton deck opens normally; Next subsequently has no effect.
        if self.card is None and len(available) == 1:
            current_id = None
        for _ in range(len(available)):
            card = choose_next(available, current_id, self.rng)
            if card is None:
                return self.card is not None
            try:
                picture = pygame.image.load(str(card.image)).convert_alpha() if card.image else None
                if picture is not None:
                    maximum = min(320, self.picture_rect.w, self.picture_rect.h)
                    scale = min(maximum / picture.get_width(), maximum / picture.get_height())
                    picture = pygame.transform.smoothscale(picture, (max(1, round(picture.get_width() * scale)),
                                                                      max(1, round(picture.get_height() * scale))))
            except (pygame.error, OSError):
                self.logger.exception("Reading illustration unavailable")
                self.bad_images.add(card.id)
                available = self._available()
                continue
            self.player.select(card)
            self.card, self.picture = card, picture
            self._prepare_word()
            return True
        self.player.cancel()
        self.card = None
        return False

    def _prepare_word(self):
        units = self.card.units
        if self.card.kind == "letters" and self.options.letter_case == "uppercase":
            units = tuple(unit.upper() for unit in units)
        gap = 6 if self.card.kind == "words" else 0
        size = min(144, self.word_rect.h - 12)
        while True:
            font = theme.ui_font(size)
            widths = [font.size(unit)[0] for unit in units]
            total = sum(widths) + gap * (len(units) - 1)
            if total <= self.word_rect.w - 20 or size <= 32:
                break
            size -= 2
        self._unit_rects, self._unit_text, self._unit_highlight = [], [], []
        x = self.word_rect.centerx - total // 2
        for unit, width in zip(units, widths):
            glyph = font.render(unit, True, theme.INK)
            box = glyph.get_rect(center=(x + width // 2, self.word_rect.centery))
            self._unit_rects.append(box)
            self._unit_text.append(glyph)
            self._unit_highlight.append(font.render(unit, True, theme.ACCENT))
            x += width + gap

    def _draw_quantity(self):
        number = self.card.number
        groups = max(1, (number + 9) // 10)
        cell = min(34, (self.picture_rect.w - 20) // 5, (self.picture_rect.h - 20) // (groups * 2 + groups - 1))
        frame_w, frame_h = cell * 5, cell * 2
        start_y = self.picture_rect.centery - (groups * frame_h + (groups - 1) * cell) // 2
        x = self.picture_rect.centerx - frame_w // 2
        for group in range(groups):
            y = start_y + group * (frame_h + cell)
            for index in range(10):
                box = pygame.Rect(x + index % 5 * cell, y + index // 5 * cell, cell, cell)
                pygame.draw.rect(self.screen, theme.BORDER, box, width=1)
                if group * 10 + index < number:
                    pygame.draw.circle(self.screen, theme.HARMONY, box.center, max(3, cell // 3))

    def render(self):
        self.screen.fill(theme.BACKGROUND)
        self.screen.blit(self.title, (24, 30))
        draw_home_button(self.screen, self.home_rect)
        theme.card(self.screen, self.panel, radius=20)
        active = self.player.active_unit
        for i, box in enumerate(self._unit_rects):
            selected = active == -1 or active == i
            if selected:
                pygame.draw.rect(self.screen, theme.SELECTED, box.inflate(8, 0), border_radius=12)
                pygame.draw.line(self.screen, theme.ACCENT, (box.left, box.bottom), (box.right, box.bottom), 4)
            self.screen.blit(self._unit_highlight[i] if selected else self._unit_text[i], box)
        if self.player.revealed:
            if self.card.kind == "numbers":
                self._draw_quantity()
            elif self.picture is not None:
                self.screen.blit(self.picture, self.picture.get_rect(center=self.picture_rect.center))
        if self.can_next:
            theme.card(self.screen, self.next_rect)
            self.screen.blit(self.arrow, self.arrow.get_rect(center=self.next_rect.center))

    def _target(self, pos):
        if self.home_rect.collidepoint(pos):
            return "home"
        if self.next_rect.collidepoint(pos) and self.can_next:
            return "next"
        if self.word_rect.collidepoint(pos):
            return "word"
        if self.picture_rect.collidepoint(pos) and self.player.revealed:
            return "picture"
        return None

    def reset_input(self):
        self.pointer.reset()
        self.pressed = None
        self.player.cancel()

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            return False
        if is_escape_chord(event) and not os.environ.get("TODDLERBOX_HEALTH_SOCKET"):
            return False
        if event.type in FOCUS_EVENTS:
            self.reset_input()
            return True
        if not self.pointer.accept(event):
            return True
        down = is_primary_pointer_event(event, is_down=True)
        up = is_primary_pointer_event(event, is_down=False)
        if not (down or up):
            return True
        pos = pointer_event_pos(event, self.rect)
        if pos is None:
            return True
        if down:
            self.pressed = (self._target(pos), pos)
            return True
        pressed, self.pressed = self.pressed, None
        if pressed is None or pressed[0] != self._target(pos) or (pygame.Vector2(pos) - pressed[1]).length() > 32:
            return True
        if pressed[0] == "home":
            return False
        if pressed[0] == "next":
            return self.next_card()
        if pressed[0] == "word":
            self.player.play()
        elif pressed[0] == "picture":
            self.player.play(whole_word=True)
        return True

    def run(self):
        global _last_card_id
        try:
            running = self.card is not None
            if not running:
                self.logger.info("No usable Reading cards; returning Home")
            previous_frame = time.monotonic()
            while running and not health.stopping():
                now = time.monotonic()
                discard_input = now - previous_frame > 2.0
                if discard_input:
                    self.reset_input()
                previous_frame = now
                for event in pygame.event.get():
                    if discard_input and event.type != pygame.QUIT:
                        continue
                    if not self.handle_event(event):
                        running = False
                        break
                    if event.type in FOCUS_EVENTS:
                        discard_input = True
                if not running or health.stopping():
                    break
                self.player.update()
                if not self._available():
                    break
                self.render()
                control.before_flip(self.screen)
                pygame.display.flip()
                health.frame_complete()
                self.clock.tick(60)
        finally:
            _last_card_id = self.card.id if self.card else None
            self.player.close()
            self.pointer.reset()
            self.pressed = None


def run_embedded(screen, screen_rect, clock):
    ReadingApp(screen, screen_rect, clock, previous_id=_last_card_id).run()


def main():
    config = load_config()
    logger = get_runtime_logger(get_data_root(config))
    try:
        screen, rect = create_fullscreen_window()
        ReadingApp(screen, rect, pygame.time.Clock(), config=config).run()
    except Exception:
        logger.exception("Reading activity failed")
    finally:
        pygame.quit()
