from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import pygame

from toddlerbox.runtime.health import install_shutdown_handlers
from toddlerbox.ui import theme


Color = Tuple[int, int, int]
Point = Tuple[int, int]

FINGERDOWN = getattr(pygame, "FINGERDOWN", None)
FINGERUP = getattr(pygame, "FINGERUP", None)
FINGERMOTION = getattr(pygame, "FINGERMOTION", None)
FINGER_EVENTS = {event for event in (FINGERDOWN, FINGERUP, FINGERMOTION) if event is not None}


class PointerInput:
    """Admit one physical pointer gesture, using SDL's raw touch stream.

    SDL sends both FINGER* and touch-emulated mouse events by default. Always
    discard the latter, including when they arrive before their finger event.
    Real mouse/trackpad events remain supported. Activities own one instance
    and reset it on focus loss or scene changes; unowned moves/ups are ignored.
    """

    def __init__(self) -> None:
        self.owner: tuple | None = None

    def reset(self) -> None:
        self.owner = None

    def accept(self, event: pygame.event.Event) -> bool:
        if event.type in FINGER_EVENTS:
            source = ("finger", getattr(event, "touch_id", 0), getattr(event, "finger_id", 0))
            down, up = event.type == FINGERDOWN, event.type == FINGERUP
        elif event.type in {pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION}:
            if getattr(event, "touch", False):
                return False
            if event.type != pygame.MOUSEMOTION and getattr(event, "button", 1) not in {0, 1}:
                return True  # Preserve wheel and other non-primary controls.
            source = ("mouse",)
            down, up = event.type == pygame.MOUSEBUTTONDOWN, event.type == pygame.MOUSEBUTTONUP
        else:
            return True
        if down:
            if self.owner is not None:
                return False
            self.owner = source
            return True
        if self.owner != source:
            return False
        if up:
            self.owner = None
        return True


@dataclass
class Button:
    rect: pygame.Rect
    label: str = ""
    image: Optional[pygame.Surface] = None
    fill: Optional[Color] = None
    border_color: Optional[Color] = theme.BORDER
    border_width: int = 1

    def draw(self, surface: pygame.Surface, font: Optional[pygame.font.Font] = None,
             *, selected: bool = False) -> None:
        if self.fill is not None:
            pygame.draw.rect(surface, theme.SELECTED if selected else self.fill,
                             self.rect, border_radius=theme.RADIUS)
        if self.image is not None:
            image_rect = self.image.get_rect(center=self.rect.center)
            surface.blit(self.image, image_rect)
        if selected or (self.border_color is not None and self.border_width > 0):
            pygame.draw.rect(
                surface,
                theme.ACCENT if selected else self.border_color,
                self.rect,
                width=2 if selected else self.border_width,
                border_radius=theme.RADIUS,
            )
        if self.label and font is not None:
            text = font.render(self.label, True, theme.INK)
            center = (self.rect.centerx, self.rect.bottom - 18) if self.image else self.rect.center
            text_rect = text.get_rect(center=center)
            surface.blit(text, text_rect)

    def hit(self, pos: Tuple[int, int]) -> bool:
        return self.rect.collidepoint(pos)


def create_fullscreen_window() -> Tuple[pygame.Surface, pygame.Rect]:
    install_shutdown_handlers()
    pygame.init()
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.mouse.set_visible(True)
    return screen, screen.get_rect()


def load_image(path: str, size: Optional[Tuple[int, int]] = None) -> Optional[pygame.Surface]:
    if not path:
        return None
    resolved = Path(path)
    if not resolved.exists():
        return None
    image = pygame.image.load(str(resolved)).convert_alpha()
    if size:
        image = pygame.transform.smoothscale(image, size)
    return image


def draw_placeholder_icon(
    surface: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    *,
    border_width: int = 0,
    border_color: Color = (40, 40, 40),
) -> None:
    theme.card(surface, rect)
    if border_width > 0:
        pygame.draw.rect(surface, border_color, rect, width=border_width, border_radius=16)
    font = theme.ui_font(22)
    text = font.render(label, True, theme.INK)
    text_rect = text.get_rect(center=rect.center)
    surface.blit(text, text_rect)


def draw_home_button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    *,
    border_width: int = 0,
    border_color: Color = (30, 30, 30),
) -> None:
    theme.card(surface, rect)
    if border_width > 0:
        pygame.draw.rect(surface, border_color, rect, width=border_width, border_radius=10)

    glyph = theme.icon("home", (max(1, rect.w - 8), max(1, rect.h - 8)))
    surface.blit(glyph, glyph.get_rect(center=rect.center))


def is_escape_chord(event: pygame.event.Event) -> bool:
    if event.type != pygame.KEYDOWN:
        return False
    if event.key != pygame.K_HOME:
        return False
    mods = event.mod
    has_ctrl = bool(mods & pygame.KMOD_CTRL)
    has_alt = bool(mods & pygame.KMOD_ALT)
    disallowed = (
        pygame.KMOD_SHIFT
        | pygame.KMOD_META
        | pygame.KMOD_GUI
        | getattr(pygame, "KMOD_ALTGR", 0)
    )
    return has_ctrl and has_alt and (mods & disallowed) == 0


def is_primary_pointer_event(event: pygame.event.Event, *, is_down: bool) -> bool:
    expected_type = pygame.MOUSEBUTTONDOWN if is_down else pygame.MOUSEBUTTONUP
    if event.type == expected_type:
        button = getattr(event, "button", 1)
        if button in {0, 1}:
            return True
        return bool(getattr(event, "touch", False))
    finger_type = FINGERDOWN if is_down else FINGERUP
    return finger_type is not None and event.type == finger_type


def pointer_event_pos(event: pygame.event.Event, screen_rect: pygame.Rect) -> Optional[Point]:
    if hasattr(event, "pos"):
        return event.pos
    if event.type in FINGER_EVENTS:
        return (
            int(event.x * screen_rect.width),
            int(event.y * screen_rect.height),
        )
    return None


def ignore_system_shortcut(event: pygame.event.Event) -> bool:
    if event.type != pygame.KEYDOWN:
        return False
    if event.key in {
        pygame.K_F1,
        pygame.K_F2,
        pygame.K_F3,
        pygame.K_F4,
        pygame.K_F5,
        pygame.K_F6,
        pygame.K_F7,
        pygame.K_F8,
        pygame.K_F9,
        pygame.K_F10,
        pygame.K_F11,
        pygame.K_F12,
    }:
        return True
    return False


def set_env_for_child() -> dict:
    import os
    env = os.environ.copy()
    env["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    return env
