"""Shared, quiet visual language for the launcher and its activities.

Artwork is loaded and scaled once per size; frames only blit it.
Document pixels and photo colors are deliberately independent of this palette.
"""
from functools import lru_cache
from pathlib import Path

import pygame

BACKGROUND = (248, 246, 238)
PAPER = (255, 253, 247)
PANEL = (239, 238, 228)
INK = (43, 59, 74)
MUTED = (115, 128, 136)
BORDER = (216, 222, 211)
SELECTED = (228, 239, 231)
ACCENT = (103, 155, 139)
MELODY = (66, 153, 175)
HARMONY = (223, 171, 81)
RADIUS = 13
MARGIN = 16


def ui_font(size: int = 20, *, bold: bool = False) -> pygame.font.Font:
    return pygame.font.SysFont("sans", size, bold=bold)


def home_rect(screen_rect: pygame.Rect) -> pygame.Rect:
    return pygame.Rect(screen_rect.right - MARGIN - 58, MARGIN, 58, 58)


def card(surface: pygame.Surface, rect: pygame.Rect, *, selected: bool = False,
         fill: tuple | None = PAPER, radius: int = RADIUS) -> None:
    if fill is not None:
        pygame.draw.rect(surface, SELECTED if selected else fill, rect, border_radius=radius)
    pygame.draw.rect(surface, ACCENT if selected else BORDER, rect,
                     width=2 if selected else 1, border_radius=radius)


def selection(surface: pygame.Surface, rect: pygame.Rect, *, radius: int = RADIUS) -> None:
    pygame.draw.rect(surface, ACCENT, rect, width=3, border_radius=radius)


@lru_cache(maxsize=32)
def artwork(kind: str, size: tuple[int, int]) -> pygame.Surface:
    """Reuse ToddlerBox's original illustrated artwork at each display size."""
    base = Path(__file__).resolve().parents[3] / "assets" / "icons"
    names = {"home": "home/home_256.png", "photos": "photos/photos_512.png",
             "music": "music/music.png", "reading": "reading/reading.png"}
    try:
        source = pygame.image.load(str(base / names[kind])).convert_alpha()
    except (pygame.error, OSError):
        # A missing decorative asset must not take away Home or the launcher.
        source = pygame.Surface((100, 100), pygame.SRCALPHA)
        if kind == "home":
            pygame.draw.polygon(source, INK, [(15, 47), (50, 16), (85, 47)])
            pygame.draw.rect(source, INK, (27, 45, 46, 39), border_radius=4)
            pygame.draw.rect(source, PAPER, (44, 60, 13, 24), border_radius=3)
        else:
            pygame.draw.rect(source, BORDER, (12, 20, 76, 60), width=4, border_radius=8)
            pygame.draw.circle(source, MELODY, (50, 50), 15)
    scale = min(size[0] / source.get_width(), size[1] / source.get_height())
    return pygame.transform.smoothscale(source, (max(1, round(source.get_width() * scale)),
                                                 max(1, round(source.get_height() * scale))))


@lru_cache(maxsize=8)
def arrow(direction: str, size: tuple[int, int]) -> pygame.Surface:
    art = pygame.Surface((120, 144), pygame.SRCALPHA)
    x = 1 if direction == "left" else -1
    pygame.draw.lines(art, INK, False,
                      [(60 + 15*x, 40), (60 - 13*x, 72), (60 + 15*x, 104)], 7)
    return pygame.transform.smoothscale(art, size)


def activity_tile(art: pygame.Surface, label: str, size: int) -> pygame.Surface:
    tile = pygame.Surface((size, size), pygame.SRCALPHA)
    card(tile, tile.get_rect(), radius=20)
    picture = pygame.Rect(4, 3, size - 8, size - 34)
    scale = min(picture.w / art.get_width(), picture.h / art.get_height())
    art = pygame.transform.smoothscale(art, (max(1, round(art.get_width() * scale)),
                                           max(1, round(art.get_height() * scale))))
    tile.blit(art, art.get_rect(center=picture.center))
    text = ui_font(20, bold=True).render(label, True, INK)
    tile.blit(text, text.get_rect(center=(size // 2, size - 18)))
    return tile
