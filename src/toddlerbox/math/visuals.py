"""Ten-frame geometry and bounded, existing Reading artwork."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pygame
from PIL import Image

from toddlerbox.math.model import MOTIFS
from toddlerbox.ui import theme

LIBRARY = Path(__file__).resolve().parents[3] / "assets/reading/images"


class Illustrations:
    def __init__(self, root=LIBRARY):
        self.sources = {}
        for name in MOTIFS:
            try:
                path = root / f"{name}.png"
                if not 0 < path.stat().st_size <= 2_000_000:
                    raise ValueError("Oversized Math illustration file")
                # Bound decoding before SDL allocates the bitmap, as Reading does.
                with Image.open(path) as header:
                    if header.format != "PNG" or not (1 <= header.width <= 1024 and 1 <= header.height <= 1024):
                        raise ValueError("Unexpected Math illustration format or dimensions")
                    header.verify()
                picture = pygame.image.load(str(path)).convert_alpha()
                bounds = picture.get_bounding_rect()
                if not bounds:
                    raise ValueError("Empty Math illustration")
                self.sources[name] = picture.subsurface(bounds).copy()
            except (pygame.error, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
                continue

    @lru_cache(maxsize=48)
    def scaled(self, name, size, removed=False):
        source = self.sources[name]
        scale = min(size / source.get_width(), size / source.get_height())
        picture = pygame.transform.smoothscale(source, (max(1, round(source.get_width()*scale)),
                                                       max(1, round(source.get_height()*scale))))
        if removed:
            picture = pygame.transform.grayscale(picture)
            picture.set_alpha(100)
        return picture

    def close(self):
        self.scaled.cache_clear()
        self.sources.clear()


def frame_geometry(number, area, *, icon_limit=48):
    """Return aligned ten-frame boxes and occupied cells in row-major order."""
    if type(number) is not int or not 0 <= number <= 100:
        raise ValueError("Quantity outside Math range")
    frame_count = max(1, (number + 9) // 10)
    gap, padding = 10, 8
    candidates = []
    for columns in range(1, frame_count + 1):
        rows = (frame_count + columns - 1) // columns
        size = min(icon_limit, (area.w - gap*(columns-1) - padding*2*columns)//(5*columns),
                   (area.h - gap*(rows-1) - padding*2*rows)//(2*rows))
        candidates.append((size, -abs(columns-rows), -columns, columns, rows))
    size, _, _, columns, rows = max(candidates)
    if size < 1:
        raise ValueError("Display area too small for ten frames")
    width, height = size*5 + padding*2, size*2 + padding*2
    total_w, total_h = columns*width + (columns-1)*gap, rows*height + (rows-1)*gap
    left, top = area.centerx-total_w//2, area.centery-total_h//2
    frames, cells = [], []
    for index in range(frame_count):
        row, column = divmod(index, columns)
        frame = pygame.Rect(left+column*(width+gap), top+row*(height+gap), width, height)
        frames.append(frame)
        for slot in range(min(10, max(0, number-index*10))):
            y, x = divmod(slot, 5)
            cells.append(pygame.Rect(frame.x+padding+x*size, frame.y+padding+y*size, size, size))
    return frames, cells, size


def draw_quantity(screen, number, area, art, motif, *, removed=0, icon_limit=48):
    if not 0 <= removed <= number:
        raise ValueError("Cannot remove objects outside original quantity")
    frames, cells, size = frame_geometry(number, area, icon_limit=icon_limit)
    for frame in frames:
        pygame.draw.rect(screen, theme.PAPER, frame, border_radius=7)
        pygame.draw.rect(screen, theme.BORDER, frame, width=1, border_radius=7)
        for column in range(1, 5):
            x = frame.left + 8 + column*size
            pygame.draw.line(screen, theme.BORDER, (x, frame.top+8), (x, frame.bottom-8))
        pygame.draw.line(screen, theme.BORDER, (frame.left+8, frame.top+8+size),
                         (frame.right-8, frame.top+8+size))
    for index, cell in enumerate(cells):
        cancelled = index >= number-removed
        picture = art.scaled(motif, max(1, size-4), cancelled)
        screen.blit(picture, picture.get_rect(center=cell.center))
        if cancelled:
            # The retained ghost is visibly removed, rather than merely disabled.
            pygame.draw.line(screen, theme.MUTED, (cell.left+3, cell.bottom-3),
                             (cell.right-3, cell.top+3), max(1, size//18))
    return cells
