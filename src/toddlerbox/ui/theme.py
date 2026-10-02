"""Shared, quiet visual language for the launcher and all four activities.

Artwork is drawn once at high resolution and scaled down; frames only blit it.
Document pixels and photo colors are deliberately independent of this palette.
"""
from functools import lru_cache

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


@lru_cache(maxsize=64)
def icon(kind: str, size: tuple[int, int]) -> pygame.Surface:
    """Original vector pictograms in a common 100-unit drawing space."""
    art = pygame.Surface((300, 300), pygame.SRCALPHA)

    def points(coords):
        return [(round(x * 3), round(y * 3)) for x, y in coords]

    def line(color, coords, width=4):
        pygame.draw.lines(art, color, False, points(coords), max(1, round(width * 3)))

    def polygon(color, coords):
        pygame.draw.polygon(art, color, points(coords))

    def rect(color, box, radius=4, width=0):
        pygame.draw.rect(art, color, [round(v * 3) for v in box],
                         width=round(width * 3), border_radius=round(radius * 3))

    def circle(color, xy, radius):
        pygame.draw.circle(art, color, points([xy])[0], round(radius * 3))

    if kind == "home":
        polygon(INK, [(17, 47), (50, 18), (83, 47), (77, 54), (50, 31), (23, 54)])
        rect(INK, (28, 44, 44, 36), 5)
        rect(PAPER, (45, 58, 13, 22), 3)
    elif kind == "paint":
        pygame.draw.ellipse(art, (237, 210, 173), (33, 57, 222, 210))
        for color, xy in [(MELODY, (31, 40)), ((210, 121, 117), (52, 33)),
                          (HARMONY, (72, 45)), (ACCENT, (30, 65))]:
            circle(color, xy, 7)
        circle(PAPER, (61, 68), 10)
        polygon(INK, [(60, 67), (86, 16), (91, 19), (69, 72)])
        polygon(MELODY, [(59, 65), (69, 72), (58, 85), (49, 83)])
    elif kind == "photos":
        rect(INK, (12, 18, 76, 64), 8)
        rect((215, 232, 229), (17, 23, 66, 54), 5)
        circle(HARMONY, (66, 37), 8)
        polygon(ACCENT, [(17, 68), (37, 43), (63, 77), (17, 77)])
        polygon(MELODY, [(41, 77), (62, 52), (83, 71), (83, 77)])
    elif kind == "typing":
        rect(PAPER, (15, 12, 70, 76), 8)
        rect(BORDER, (15, 12, 70, 76), 8, 2)
        polygon(INK, [(25, 63), (39, 27), (46, 27), (60, 63), (52, 63),
                      (49, 54), (36, 54), (33, 63)])
        polygon(PAPER, [(39, 46), (46, 46), (42, 35)])
        line(MELODY, [(66, 34), (66, 65)], 3)
        line(BORDER, [(27, 75), (73, 75)], 2)
    elif kind == "music":
        rect(INK, (10, 52, 80, 35), 5)
        for i in range(7):
            rect(PAPER, (13 + i * 10.7, 55, 9.4, 29), 2)
        for i in [0, 1, 3, 4, 5]:
            rect(INK, (20 + i * 10.7, 55, 6.5, 18), 1)
        line(MELODY, [(42, 37), (42, 17), (66, 12), (66, 32)], 4)
        pygame.draw.ellipse(art, MELODY, (90, 96, 42, 30))
        pygame.draw.ellipse(art, MELODY, (162, 81, 42, 30))
    elif kind == "round":
        polygon(INK, [(39, 61), (70, 13), (81, 22), (50, 68)])
        polygon(BORDER, [(35, 61), (46, 51), (57, 60), (48, 74)])
        polygon(MELODY, [(35, 64), (49, 75), (40, 87), (18, 86), (29, 77)])
    elif kind == "fountain":
        polygon(INK, [(39, 42), (72, 12), (88, 28), (58, 60)])
        polygon(HARMONY, [(39, 40), (60, 61), (30, 82), (18, 83), (20, 70)])
        line(INK, [(22, 79), (42, 59)], 2)
        circle(INK, (43, 58), 3)
    elif kind == "eraser":
        polygon((208, 150, 151), [(17, 59), (50, 22), (83, 49), (49, 85)])
        polygon(PAPER, [(17, 59), (34, 41), (67, 68), (49, 85)])
        line(INK, [(17, 59), (49, 85), (75, 85)], 3)
    elif kind == "bucket":
        polygon(MELODY, [(20, 51), (50, 21), (78, 49), (48, 79)])
        line(INK, [(25, 42), (20, 25), (28, 16), (42, 16), (57, 35)], 3)
        line(PAPER, [(23, 51), (48, 75)], 4)
        polygon(HARMONY, [(79, 59), (69, 78), (71, 85), (82, 87), (87, 80)])
    elif kind in {"left", "right"}:
        x = 1 if kind == "left" else -1
        line(INK, [(50 + 12*x, 28), (50 - 10*x, 50), (50 + 12*x, 72)], 5)
    elif kind.startswith("size-"):
        width = {"size-0": 3, "size-1": 7, "size-2": 13}[kind]
        line(INK, [(50, 20), (50, 80)], width)
        circle(INK, (50, 20), width / 2)
        circle(INK, (50, 80), width / 2)
    else:
        raise ValueError(f"Unknown UI pictogram: {kind}")
    return pygame.transform.smoothscale(art, size)


def activity_tile(kind: str, label: str, size: int) -> pygame.Surface:
    tile = pygame.Surface((size, size), pygame.SRCALPHA)
    card(tile, tile.get_rect(), radius=20)
    colors = {"paint": (246, 231, 211), "photos": (222, 237, 228),
              "typing": (231, 229, 242), "music": (218, 236, 230)}
    picture = pygame.Rect(14, 12, size - 28, size - 49)
    pygame.draw.rect(tile, colors[kind], picture, border_radius=15)
    glyph_size = min(picture.size) - 6
    glyph = icon(kind, (glyph_size, glyph_size))
    tile.blit(glyph, glyph.get_rect(center=picture.center))
    text = ui_font(20, bold=True).render(label, True, INK)
    tile.blit(text, text.get_rect(center=(size // 2, size - 22)))
    return tile
