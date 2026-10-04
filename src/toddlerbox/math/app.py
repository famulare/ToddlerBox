from __future__ import annotations

import os
import random
import time

import pygame

from toddlerbox.config import load_config
from toddlerbox.math.model import MODES, choose_next, options_from_config
from toddlerbox.math.speech import NumberPlayer
from toddlerbox.math.visuals import Illustrations, draw_quantity, frame_geometry
from toddlerbox.paths import get_data_root
from toddlerbox.runtime import control, get_runtime_logger, health
from toddlerbox.ui import theme
from toddlerbox.ui.common import (PointerInput, create_fullscreen_window, draw_home_button,
                                  is_escape_chord, is_primary_pointer_event, pointer_event_pos)

FOCUS_EVENTS = {getattr(pygame, name, -1) for name in
                ("WINDOWFOCUSLOST", "WINDOWFOCUSGAINED", "APP_DIDENTERFOREGROUND", "APP_WILLENTERBACKGROUND")}
MODE_LABELS = {"numbers": "Numbers", "addition": "+", "subtraction": "−"}


class MathApp:
    def __init__(self, screen, screen_rect, clock, *, config=None, rng=None, library=None, player=None):
        self.screen, self.rect, self.clock = screen, screen_rect, clock
        self.config = load_config() if config is None else config
        self.logger = get_runtime_logger(get_data_root(self.config))
        self.options = options_from_config(self.config, self.logger)
        self.player = NumberPlayer(self.logger, volume=self.options.volume) if player is None else player
        self.mode = self.options.mode
        self.rng = random.Random() if rng is None else rng
        self.art = Illustrations() if library is None else Illustrations(library)
        self.example = None
        self.revealed = False
        self.pointer = PointerInput()
        self.pressed = None
        self.home_rect = theme.home_rect(self.rect)
        self.mode_rect = pygame.Rect(self.rect.centerx-80, 16, 160, 58)
        self.speech_rect = pygame.Rect(self.mode_rect.right+16, 16, 58, 58)
        self.question_rect = pygame.Rect(24, 98, self.rect.w-128, 108)
        self.next_rect = pygame.Rect(self.rect.right-80, 123, 58, 58)
        self.body_rect = pygame.Rect(24, 226, self.rect.w-48, self.rect.h-250)
        self.arrow = theme.arrow("right", (42, 48))
        self.next_example()

    @property
    def can_next(self):
        return self.options.max_number > 0

    def reset_input(self):
        self.pointer.reset()
        self.pressed = None

    def next_example(self):
        self.reset_input()
        self.player.cancel()
        if not self.art.sources:
            self.example = None
            return
        example = choose_next(self.mode, self.options, self.rng, self.example,
                              motifs=tuple(self.art.sources))
        if example is not None:
            self.example = example
            self.revealed = False

    def change_mode(self):
        self.mode = MODES[(MODES.index(self.mode)+1) % len(MODES)]
        self.next_example()

    def reveal(self):
        self.revealed = True

    def _question(self):
        e = self.example
        if e.mode == "numbers":
            return str(e.a) if self.revealed else "?"
        symbol = "+" if e.mode == "addition" else "−"
        return f"{e.a} {symbol} {e.b} = {e.result if self.revealed else '?'}"

    def _text(self, text, rect, size=72, color=theme.INK):
        font = theme.ui_font(size)
        while font.size(text)[0] > rect.w-16 and size > 18:
            size -= 2
            font = theme.ui_font(size)
        glyph = font.render(text, True, color)
        self.screen.blit(glyph, glyph.get_rect(center=rect.center))

    def quantity_panels(self):
        if self.mode == "numbers":
            return [self.body_rect]
        # At 800×600 the shared cell size remains at least 18px even for 100.
        columns = 3 if self.mode == "addition" else 2
        gap = 16
        width = (self.body_rect.w-gap*(columns-1))//columns
        return [pygame.Rect(self.body_rect.x+i*(width+gap), self.body_rect.y, width, self.body_rect.h)
                for i in range(columns)]

    def render(self):
        self.screen.fill(theme.BACKGROUND)
        title = theme.ui_font(28, bold=True).render("Math", True, theme.INK)
        self.screen.blit(title, (24, 30))
        draw_home_button(self.screen, self.home_rect)
        theme.card(self.screen, self.mode_rect)
        self._text(MODE_LABELS[self.mode], self.mode_rect.move(-12, 0), 28)
        self._text("›", pygame.Rect(self.mode_rect.right-34, self.mode_rect.y, 28, 58), 28)
        if self.example is None:
            return
        if self.revealed:
            theme.card(self.screen, self.speech_rect)
            x, y = self.speech_rect.center
            pygame.draw.rect(self.screen, theme.INK, (x-16, y-5, 8, 10), border_radius=2)
            pygame.draw.polygon(self.screen, theme.INK, [(x-8,y-5),(x,y-13),(x,y+13),(x-8,y+5)])
            pygame.draw.arc(self.screen, theme.INK, (x-10,y-16,28,32), -0.85, 0.85, 3)
        theme.card(self.screen, self.question_rect)
        self._text(self._question(), self.question_rect)
        if self.can_next:
            theme.card(self.screen, self.next_rect)
            self.screen.blit(self.arrow, self.arrow.get_rect(center=self.next_rect.center))
        e = self.example
        panels = self.quantity_panels()
        for panel in panels:
            theme.card(self.screen, panel, fill=theme.PANEL)
        areas = [p.inflate(-12, -20) for p in panels]
        if self.mode == "numbers":
            draw_quantity(self.screen, e.a, areas[0], self.art, e.motif)
            return
        quantities = [e.a, e.b, e.result] if self.mode == "addition" else [e.a, e.result]
        size = min(frame_geometry(n, area)[2] for n, area in zip(quantities, areas))
        draw_quantity(self.screen, e.a, areas[0], self.art, e.motif,
                      removed=e.b if self.mode == "subtraction" and self.revealed else 0, icon_limit=size)
        if self.mode == "addition":
            draw_quantity(self.screen, e.b, areas[1], self.art, e.motif, icon_limit=size)
        if self.revealed:
            draw_quantity(self.screen, e.result, areas[-1], self.art, e.motif, icon_limit=size)
        else:
            self._text("?", panels[-1], 64, theme.MUTED)

    def _target(self, pos):
        for name, rect in (("home", self.home_rect), ("mode", self.mode_rect),
                           ("reveal", self.question_rect)):
            if rect.collidepoint(pos):
                return name
        if self.revealed and self.speech_rect.collidepoint(pos):
            return "speech"
        if self.can_next and self.next_rect.collidepoint(pos):
            return "next"
        return None  # Objects and frames deliberately have no touch action.

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.player.cancel()
            return False
        if is_escape_chord(event) and not os.environ.get("TODDLERBOX_HEALTH_SOCKET"):
            return False
        if event.type in FOCUS_EVENTS:
            self.reset_input()
            self.player.cancel()
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
            self.pressed = self._target(pos), pos
            return True
        pressed, self.pressed = self.pressed, None
        if pressed is None or pressed[0] != self._target(pos) or (pygame.Vector2(pos)-pressed[1]).length() > 24:
            return True
        if pressed[0] == "home":
            self.player.cancel()
            return False
        if pressed[0] == "next":
            self.next_example()
        elif pressed[0] == "mode":
            self.change_mode()
        elif pressed[0] == "speech":
            self.player.play(self.example.result)
        elif pressed[0] == "reveal":
            self.reveal()
        return True

    def run(self):
        try:
            running = self.example is not None
            if not running:
                self.logger.info("No usable Math illustrations; returning Home")
            previous_frame = time.monotonic()
            while running and not health.stopping():
                now = time.monotonic()
                discard_input = now-previous_frame > 2.0
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
                self.render()
                control.before_flip(self.screen)  # No child work to save; existing authenticated ACK.
                pygame.display.flip()
                health.frame_complete()
                self.clock.tick(60)
        finally:
            self.reset_input()
            self.player.cancel()
            self.art.close()


def run_embedded(screen, screen_rect, clock):
    MathApp(screen, screen_rect, clock).run()


def main():
    config = load_config()
    logger = get_runtime_logger(get_data_root(config))
    try:
        screen, rect = create_fullscreen_window()
        MathApp(screen, rect, pygame.time.Clock(), config=config).run()
    except Exception:
        logger.exception("Math activity failed")
    finally:
        pygame.quit()
