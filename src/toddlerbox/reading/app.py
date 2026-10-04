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
        self.rail_offset = 0
        self.rail_images = False
        self.thumbnails = {}
        self._scroll_y = None
        self.bad_images: set[str] = set()
        self.card = None
        self.picture = None
        self.home_rect = theme.home_rect(self.rect)
        margin = max(16, min(32, self.rect.w // 32))
        arrow_width = 80
        rail_width = max(158, min(216, self.rect.w // 5))
        self.words_toggle = pygame.Rect(margin, 100, (rail_width - 8)//2, 48)
        self.images_toggle = pygame.Rect(self.words_toggle.right + 8, 100, (rail_width - 8)//2, 48)
        self.rail = pygame.Rect(margin, 160, rail_width, self.rect.h - 160 - margin)
        self.panel = pygame.Rect(self.rail.right + margin, 100, self.rect.w - rail_width - margin * 4 - arrow_width,
                                 self.rect.h - 100 - margin)
        self.next_rect = pygame.Rect(self.panel.right + margin, self.panel.centery - 40, arrow_width, 80)
        self.word_rect = pygame.Rect(self.panel.x + 16, self.panel.y + 16, self.panel.w - 32,
                                     max(120, min(180, self.panel.h // 3)))
        self.read_rect = pygame.Rect(self.panel.centerx - 56, self.word_rect.bottom + 4, 112, 48)
        self.picture_rect = pygame.Rect(self.panel.x + 20, self.read_rect.bottom + 12,
                                        self.panel.w - 40, self.panel.bottom - self.read_rect.bottom - 32)
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
            if self.select_card(card):
                return True
            available = self._available()
        self.player.cancel()
        self.card = None
        return False

    def select_card(self, card):
        try:
            picture = pygame.image.load(str(card.image)).convert_alpha() if card.image else None
            if picture is not None:
                maximum = min(320, self.picture_rect.w, self.picture_rect.h)
                scale = min(maximum / picture.get_width(), maximum / picture.get_height())
                picture = pygame.transform.smoothscale(picture, (max(1, round(picture.get_width()*scale)),
                                                                  max(1, round(picture.get_height()*scale))))
        except (pygame.error, OSError):
            self.logger.exception("Reading illustration unavailable")
            self.bad_images.add(card.id)
            return False
        self.player.select(card)
        self.card, self.picture = card, picture
        self._prepare_word()
        return True

    def _scroll(self, delta):
        maximum = max(0, len(self.cards)*76 - self.rail.h)
        self.rail_offset = max(0, min(maximum, self.rail_offset + delta))

    def _rail_rows(self):
        for i, card in enumerate(self.cards):
            row = pygame.Rect(self.rail.x, self.rail.y + i*76 - int(self.rail_offset), self.rail.w, 68)
            if row.colliderect(self.rail):
                yield card, row

    def _draw_rail(self):
        for rect, label, selected in [(self.words_toggle, "abc", not self.rail_images),
                                      (self.images_toggle, "Pictures", self.rail_images)]:
            theme.card(self.screen, rect, selected=selected)
            glyph = theme.ui_font(18, bold=True).render(label, True, theme.INK)
            self.screen.blit(glyph, glyph.get_rect(center=rect.center))
        old_clip = self.screen.get_clip()
        self.screen.set_clip(self.rail)
        for card, row in self._rail_rows():
            theme.card(self.screen, row, selected=self.card is not None and card.id == self.card.id)
            if self.rail_images and card.image and card.id not in self.bad_images:
                if card.id not in self.thumbnails:
                    try:
                        image = pygame.image.load(str(card.image)).convert_alpha()
                        self.thumbnails[card.id] = pygame.transform.smoothscale(image, (56, 56))
                    except (pygame.error, OSError):
                        self.bad_images.add(card.id)
                        self.logger.exception("Reading preview unavailable")
                image = self.thumbnails.get(card.id)
                if image is not None:
                    self.screen.blit(image, image.get_rect(center=row.center))
                    continue
            text = card.text.upper() if card.kind == "letters" and self.options.letter_case == "uppercase" else card.text
            glyph = theme.ui_font(28).render(text, True, theme.INK)
            self.screen.blit(glyph, glyph.get_rect(center=row.center))
        self.screen.set_clip(old_clip)

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

    def render(self):
        self.screen.fill(theme.BACKGROUND)
        self.screen.blit(self.title, (24, 30))
        draw_home_button(self.screen, self.home_rect)
        self._draw_rail()
        theme.card(self.screen, self.panel, radius=20)
        active = self.player.active_unit
        for i, box in enumerate(self._unit_rects):
            selected = active == -1 or active == i
            if selected:
                pygame.draw.rect(self.screen, theme.SELECTED, box.inflate(8, 0), border_radius=12)
                pygame.draw.line(self.screen, theme.ACCENT, (box.left, box.bottom), (box.right, box.bottom), 4)
            self.screen.blit(self._unit_highlight[i] if selected else self._unit_text[i], box)
        theme.card(self.screen, self.read_rect)
        # A deliberate whole-word tap is distinct from the large sound units.
        glyph = theme.ui_font(24).render(self.card.text, True, theme.INK)
        if glyph.get_width() > self.read_rect.w - 12:
            glyph = pygame.transform.smoothscale(glyph, (self.read_rect.w - 12, glyph.get_height()))
        self.screen.blit(glyph, glyph.get_rect(center=self.read_rect.center))
        if self.player.revealed:
            if self.picture is not None:
                self.screen.blit(self.picture, self.picture.get_rect(center=self.picture_rect.center))
        if self.can_next:
            theme.card(self.screen, self.next_rect)
            self.screen.blit(self.arrow, self.arrow.get_rect(center=self.next_rect.center))

    def _target(self, pos):
        if self.home_rect.collidepoint(pos):
            return "home"
        if self.next_rect.collidepoint(pos) and self.can_next:
            return "next"
        if self.words_toggle.collidepoint(pos):
            return "words-toggle"
        if self.images_toggle.collidepoint(pos):
            return "images-toggle"
        if self.rail.collidepoint(pos):
            for card, row in self._rail_rows():
                if row.collidepoint(pos) and card.id not in self.bad_images | self.player.failed:
                    return ("select", card.id)
        if self.read_rect.collidepoint(pos):
            return "word"
        if self.word_rect.collidepoint(pos) and self._unit_rects:
            return ("unit", min(range(len(self._unit_rects)), key=lambda i: abs(self._unit_rects[i].centerx - pos[0])))
        if self.picture_rect.collidepoint(pos) and self.player.revealed:
            return "picture"
        return None

    def reset_input(self):
        self.pointer.reset()
        self.pressed = None
        self._scroll_y = None
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
        if event.type == pygame.MOUSEWHEEL:
            self._scroll(-event.y * 76)
            return True
        pos = pointer_event_pos(event, self.rect)
        if event.type in {pygame.MOUSEMOTION, pygame.FINGERMOTION} and self._scroll_y is not None and pos is not None:
            self._scroll(self._scroll_y - pos[1])
            self._scroll_y = pos[1]
            if self.pressed and abs(pos[1] - self.pressed[1][1]) > 8:
                self.pressed = None
            return True
        down = is_primary_pointer_event(event, is_down=True)
        up = is_primary_pointer_event(event, is_down=False)
        if not (down or up):
            return True
        if pos is None:
            return True
        if down:
            self.pressed = (self._target(pos), pos)
            self._scroll_y = pos[1] if self.rail.collidepoint(pos) else None
            return True
        self._scroll_y = None
        pressed, self.pressed = self.pressed, None
        if pressed is None or pressed[0] != self._target(pos) or (pygame.Vector2(pos) - pressed[1]).length() > 32:
            return True
        if pressed[0] == "home":
            return False
        if pressed[0] == "next":
            return self.next_card()
        if pressed[0] == "word":
            self.player.cancel()
            self.player.play(whole_word=True)
        elif pressed[0] == "picture":
            self.player.cancel()
            self.player.play(whole_word=True)
        elif pressed[0] == "words-toggle":
            self.rail_images = False
        elif pressed[0] == "images-toggle":
            self.rail_images = True
        elif isinstance(pressed[0], tuple):
            kind, value = pressed[0]
            if kind == "unit":
                self.player.play_unit(value)
            elif kind == "select":
                self.select_card(next(card for card in self.cards if card.id == value))
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
