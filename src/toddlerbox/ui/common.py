from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import pygame

from toddlerbox.runtime.health import install_shutdown_handlers


Color = Tuple[int, int, int]
Point = Tuple[int, int]

_HOME_ICON_ORIG: Optional[pygame.Surface] = None
_HOME_ICON: Optional[pygame.Surface] = None
_HOME_ICON_SIZE: Optional[Tuple[int, int]] = None
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
    border_color: Optional[Color] = (30, 30, 30)
    border_width: int = 0

    def draw(self, surface: pygame.Surface, font: Optional[pygame.font.Font] = None) -> None:
        if self.fill is not None:
            pygame.draw.rect(surface, self.fill, self.rect, border_radius=12)
        if self.image is not None:
            image_rect = self.image.get_rect(center=self.rect.center)
            surface.blit(self.image, image_rect)
        if self.border_color is not None and self.border_width > 0:
            pygame.draw.rect(
                surface,
                self.border_color,
                self.rect,
                width=self.border_width,
                border_radius=12,
            )
        if self.label and font is not None:
            text = font.render(self.label, True, (20, 20, 20))
            text_rect = text.get_rect(center=(self.rect.centerx, self.rect.bottom - 18))
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
    pygame.draw.rect(surface, (220, 220, 220), rect, border_radius=16)
    if border_width > 0:
        pygame.draw.rect(surface, border_color, rect, width=border_width, border_radius=16)
    font = pygame.font.SysFont("sans", 22)
    text = font.render(label, True, (30, 30, 30))
    text_rect = text.get_rect(center=rect.center)
    surface.blit(text, text_rect)


def draw_home_button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    *,
    border_width: int = 0,
    border_color: Color = (30, 30, 30),
) -> None:
    pygame.draw.rect(surface, (240, 240, 240), rect, border_radius=10)
    if border_width > 0:
        pygame.draw.rect(surface, border_color, rect, width=border_width, border_radius=10)

    padding = 4
    max_w = max(1, rect.width - padding)
    max_h = max(1, rect.height - padding)
    icon_size = (max_w, max_h)
    global _HOME_ICON_ORIG, _HOME_ICON, _HOME_ICON_SIZE
    if _HOME_ICON_ORIG is None:
        icon_path = Path(__file__).resolve().parents[3] / "assets" / "icons" / "home" / "home_256.png"
        _HOME_ICON_ORIG = load_image(str(icon_path))
    if _HOME_ICON_ORIG is not None and (_HOME_ICON is None or _HOME_ICON_SIZE != icon_size):
        orig_w, orig_h = _HOME_ICON_ORIG.get_size()
        scale = min(max_w / orig_w, max_h / orig_h)
        target = (max(1, int(orig_w * scale)), max(1, int(orig_h * scale)))
        _HOME_ICON = pygame.transform.smoothscale(_HOME_ICON_ORIG, target)
        _HOME_ICON_SIZE = icon_size

    if _HOME_ICON is not None:
        image_rect = _HOME_ICON.get_rect(center=rect.center)
        surface.blit(_HOME_ICON, image_rect)
        return

    roof = [
        (rect.centerx, rect.top + 8),
        (rect.left + 8, rect.centery),
        (rect.right - 8, rect.centery),
    ]
    pygame.draw.polygon(surface, (50, 50, 50), roof)
    body = pygame.Rect(rect.left + 12, rect.centery, rect.width - 24, rect.height - 16)
    pygame.draw.rect(surface, (50, 50, 50), body, width=2)


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
