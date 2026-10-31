from __future__ import annotations

import hashlib
import io
import math
import os
import time
from concurrent.futures import Future, wait as wait_futures
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

import pygame
from PIL import Image

from toddlerbox.config import load_config
from toddlerbox.paths import ensure_directories, get_data_root
from toddlerbox.runtime import RuntimeLogger, get_runtime_logger
from toddlerbox.runtime import health, control, retained
from toddlerbox.runtime.image_safety import DECODE_ERRORS, MAX_PHOTO_PIXELS
from toddlerbox.runtime.workers import DaemonExecutor
from toddlerbox.runtime.paint_timing import PaintTiming
from toddlerbox.runtime.persistence import (
    confirm_durable,
    has_archive_reserve,
    is_work_name,
    publish_new_bytes,
    quarantine,
    recover_orphans,
    write_bytes,
)
from toddlerbox.ui import theme
from toddlerbox.ui.common import (
    Button,
    FINGER_EVENTS,
    PointerInput,
    create_fullscreen_window,
    draw_home_button,
    escape_exits,
    ignore_system_shortcut,
    is_primary_pointer_event,
    pointer_event_pos,
)


Color = Tuple[int, int, int]
Point = Tuple[int, int]

FINGERMOTION = getattr(pygame, "FINGERMOTION", None)
WINDOW_FOCUS_LOST = getattr(pygame, "WINDOWFOCUSLOST", None)
APP_DID_ENTER_BACKGROUND = getattr(pygame, "APP_DIDENTERBACKGROUND", None)

# Only actual loss of input ownership cancels a gesture. SDL also sends benign
# focus-gained/restored/size notifications while a finger can still be down.
# Treating those as loss discarded both the stroke and its queued motion/up.
_INPUT_RESET_EVENTS = {
    event
    for event in (
        WINDOW_FOCUS_LOST,
        APP_DID_ENTER_BACKGROUND,
    )
    if event is not None
}
_NOISY_KEY_MODS = (
    pygame.KMOD_CTRL
    | pygame.KMOD_ALT
    | pygame.KMOD_META
    | pygame.KMOD_GUI
    | getattr(pygame, "KMOD_ALTGR", 0)
)
_MODIFIER_KEYS = {
    getattr(pygame, "K_LCTRL", None),
    getattr(pygame, "K_RCTRL", None),
    getattr(pygame, "K_LALT", None),
    getattr(pygame, "K_RALT", None),
    getattr(pygame, "K_LGUI", None),
    getattr(pygame, "K_RGUI", None),
    getattr(pygame, "K_LMETA", None),
    getattr(pygame, "K_RMETA", None),
}

# --- Tuning constants ---
DRAG_THRESHOLD = 10
UNDO_MAX_DEPTH = 10
FOUNTAIN_SMOOTHING = 0.35
FOUNTAIN_DENSITY = 1.5
SCROLL_STEP = 40
MAX_ARCHIVES = 100
ICON_CACHE_MAX_ENTRIES = 128
_ICON_CACHE: Dict[Tuple[str, Tuple[int, int], bool], pygame.Surface] = {}



def _fountain_width_for_direction(
    size: int,
    start: Point,
    end: Point,
    *,
    nib_angle_degrees: float = 35.0,
    min_ratio: float = 0.2,
    max_ratio: float = 1.8,
) -> int:
    return _fountain_width_for_delta(size, end[0] - start[0], end[1] - start[1],
                                     nib_angle_degrees, min_ratio, max_ratio)


@lru_cache(maxsize=512)
def _fountain_width_for_delta(size: int, dx: int, dy: int,
                              nib_angle_degrees: float, min_ratio: float, max_ratio: float) -> int:
    # Densified steps repeat a handful of directions. Cache their exact nib
    # width calculation, retaining all input points and the original geometry.
    if dx == 0 and dy == 0:
        return max(1, int(round(size * ((min_ratio + max_ratio) / 2))))

    direction = math.atan2(dy, dx)
    nib_angle = math.radians(nib_angle_degrees)
    delta = direction - nib_angle
    # Broad-edge nib behavior: narrow parallel to nib axis, wide when crossing it.
    blend = abs(math.sin(delta))
    ratio = min_ratio + (max_ratio - min_ratio) * blend
    return max(1, int(round(size * ratio)))


@dataclass
class Stroke:
    tool: str
    size: int
    color: Color
    points: List[Point]
    fountain_width: float = 0.0


@dataclass
class RecallItem:
    thumb: Optional[pygame.Surface]
    source: Optional[Path] = None


def _encode_png(pixels: bytes, size: Tuple[int, int]) -> bytes:
    # Encode in memory: pygame.image.save returns normally after a short write,
    # which would let a truncated file replace the previous complete painting.
    buffer = io.BytesIO()
    Image.frombytes("RGB", size, pixels).save(buffer, format="PNG")
    return buffer.getvalue()


def _save_pixels_atomic(pixels: bytes, size: Tuple[int, int], path: Path) -> None:
    write_bytes(path, _encode_png(pixels, size))


def _canvas_pixels(surface: pygame.Surface) -> bytes:
    return pygame.image.tobytes(surface, "RGB")


def _valid_png(data: bytes) -> bool:
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or image.width * image.height > MAX_PHOTO_PIXELS:
            return False
        image.load()
    return True


def _archive_name() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S") + ".png"


def _is_paint_archive(path: Path) -> bool:
    return path.name != "latest.png" and is_work_name(path.name)


KNOWN_ARCHIVES = 8
EXIT_GRACE_SECONDS = 1.0  # A healthy save finishes well within this; then Home parks the work.
SHUTDOWN_WAIT_SECONDS = 0.75  # Per wait at TERM; the launcher must ack within the controller's grace.


class ArchiveResult(NamedTuple):
    loaded: Optional[Tuple[Tuple[int, int], bytes]]
    published: Optional[Path]
    digest: str


def _pixels_digest(pixels: bytes) -> str:
    return hashlib.sha256(pixels).hexdigest()


def _archive_duplicate(pixels: bytes, size: Tuple[int, int], directory: Path,
                       known: Tuple[Tuple[Path, str], ...], digest: str) -> bool:
    """Blank, or identical to an archive that still exists: nothing new to preserve.

    Checked before capacity so repeated New/Recall taps never fill the archive.
    """
    if pixels.count(255) == len(pixels):
        return True
    for path, known_digest in known:
        if known_digest == digest and path.exists():
            # A visible archive whose commit was uncertain does not yet replace current work.
            return confirm_durable(path)
    archives = [path for path in _list_archives(directory) if _is_paint_archive(path)]
    if not archives:
        return False
    try:
        with Image.open(archives[0]) as newest:
            if newest.size != tuple(size) or newest.width * newest.height > MAX_PHOTO_PIXELS:
                return False
            same = _pixels_digest(newest.convert("RGB").tobytes()) == digest
    except Exception:
        return False
    return same and confirm_durable(archives[0])


def _archive_pixels(pixels: bytes, size: Tuple[int, int], directory: Path,
                    limit: int, source: Optional[Path] = None,
                    known: Tuple[Tuple[Path, str], ...] = ()) -> ArchiveResult:
    """Immutable worker inputs only; decode before archiving/replacing work."""
    loaded = None
    if source is not None:
        with Image.open(source) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError("Recalled painting exceeds decoding budget")
            loaded = (image.size, image.convert("RGBA").tobytes())
    digest = _pixels_digest(pixels)
    if _archive_duplicate(pixels, size, directory, known, digest):
        return ArchiveResult(loaded, None, digest)
    archives = [path for path in _list_archives(directory) if _is_paint_archive(path)]
    if len(archives) >= limit or not has_archive_reserve(directory, size[0] * size[1] * 4 + 65536):
        raise OSError("Paint archive capacity/reserve reached")
    published = publish_new_bytes(directory / _archive_name(), _encode_png(pixels, size))
    return ArchiveResult(loaded, published, digest)


def _list_archives(paint_dir: Path) -> List[Path]:
    files = list(paint_dir.glob("*.png"))
    files.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return files


def _rollover_latest_snapshot(paint_dir: Path, now: Optional[datetime] = None) -> Optional[Path]:
    latest_path = paint_dir / "latest.png"
    if not latest_path.exists():
        return None
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    archive_path = paint_dir / f"{stamp}.png"
    counter = 1
    while archive_path.exists():
        archive_path = paint_dir / f"{stamp}_{counter}.png"
        counter += 1
    try:
        os.replace(latest_path, archive_path)
    except OSError:
        return None
    return archive_path


def _coerce_archive_limit(value: object, default: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(1, limit)


def _load_icon(path: Path, size: Tuple[int, int], *, preserve_aspect: bool = True) -> Optional[pygame.Surface]:
    if not path.exists():
        return None
    key = (str(path), size, preserve_aspect)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        image = pygame.image.load(str(path)).convert_alpha()
    except pygame.error:
        return None
    max_w, max_h = size
    if preserve_aspect:
        width, height = image.get_size()
        scale = min(max_w / width, max_h / height)
        target = (max(1, int(width * scale)), max(1, int(height * scale)))
        image = pygame.transform.smoothscale(image, target)
    else:
        image = pygame.transform.smoothscale(image, (max_w, max_h))
    if len(_ICON_CACHE) >= ICON_CACHE_MAX_ENTRIES:
        oldest_key = next(iter(_ICON_CACHE))
        _ICON_CACHE.pop(oldest_key, None)
    _ICON_CACHE[key] = image
    return image


def _draw_stamp(
    surface: pygame.Surface,
    kind: str,
    size: int,
    color: Color,
    pos: Point,
    pressure: float = 1.0,
) -> None:
    size = max(2, int(size * pressure))
    pygame.draw.circle(surface, color, pos, size // 2)


def _draw_segment(surface: pygame.Surface, stroke: Stroke, start: Point, end: Point) -> None:
    distance = max(1, pygame.math.Vector2(end).distance_to(start))
    steps = max(1, int(distance / 2))
    for idx in range(steps + 1):
        t = idx / steps
        x = int(start[0] + (end[0] - start[0]) * t)
        y = int(start[1] + (end[1] - start[1]) * t)
        pressure = 1.0
        kind = stroke.tool
        if kind == "eraser":
            kind = "round"
        _draw_stamp(surface, kind, stroke.size, stroke.color, (x, y), pressure=pressure)


def _draw_fountain_segment(
    surface: pygame.Surface,
    color: Color,
    start: Point,
    end: Point,
    start_width: float,
    end_width: float,
    *, start_cap: bool = True,
) -> None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    half_start = max(0.5, start_width * 0.5)
    half_end = max(0.5, end_width * 0.5)

    if length < 1e-6:
        radius = max(1, int(round(max(half_start, half_end))))
        pygame.draw.circle(surface, color, start, radius)
        return

    nx = -dy / length
    ny = dx / length
    quad = [
        (start[0] + nx * half_start, start[1] + ny * half_start),
        (start[0] - nx * half_start, start[1] - ny * half_start),
        (end[0] - nx * half_end, end[1] - ny * half_end),
        (end[0] + nx * half_end, end[1] + ny * half_end),
    ]
    points = [(int(round(x)), int(round(y))) for x, y in quad]
    pygame.draw.polygon(surface, color, points)

    # Round joins avoid tiny corner spikes. Internal densified steps may omit
    # the start cap: the previous step already painted that exact circle.
    if start_cap:
        pygame.draw.circle(surface, color, (int(round(start[0])), int(round(start[1]))), max(1, int(round(half_start))))
    pygame.draw.circle(surface, color, (int(round(end[0])), int(round(end[1]))), max(1, int(round(half_end))))


def _bucket_fill(surface: pygame.Surface, pos: Point, color: Color) -> None:
    if surface.get_bytesize() < 3:
        # Preserve original mapped-pixel behavior for palette and RGB565.
        _bucket_fill_small_format(surface, pos, color)
        return
    width, height = surface.get_size()
    x, y = pos
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    target = surface.get_at((x, y))[:3]
    if target == color:
        return
    target_mapped = surface.map_rgb(target)
    replacement = surface.map_rgb(color)
    if surface.get_masks()[3]:
        alpha_source = surface
        if surface.get_colorkey() is not None:
            alpha_source = surface.copy()
            alpha_source.set_colorkey(None)
        if pygame.mask.from_surface(alpha_source, 254).count() != width * height:
            # Paint produces opaque PNGs. Preserve the old exact behavior for
            # arbitrary translucent surfaces rather than changing their borders.
            _bucket_fill_small_format(surface, pos, color)
            return
        # Opaque restored PNGs must behave like fresh RGB canvases. pygame's
        # signed map_rgb vs unsigned PixelArray equality formerly filled only
        # the seed on these otherwise ordinary paintings.
    # Build exact matches in C, then walk *runs*, not Python pixels. The mask
    # is consumed on discovery so adjacent rows cannot queue the same run twice.
    # Four-neighbour scanlines preserve diagonal boundaries (mask's built-in
    # connected_component uses eight neighbours and would change Paint's fill).
    matches = pygame.mask.from_threshold(surface, target_mapped, (1, 1, 1, 1))
    indexed = pygame.Surface((width, height), depth=8)
    matches.to_surface(indexed, setcolor=1, unsetcolor=0)
    remaining = bytearray(pygame.image.tobytes(indexed, "P"))
    pixels = pygame.PixelArray(surface)

    def discover(px: int, py: int) -> tuple[int, int, int]:
        start, stop = py * width, (py + 1) * width
        at = start + px
        previous = remaining.rfind(b"\0", start, at)
        left = start if previous == -1 else previous + 1
        right = remaining.find(b"\0", at + 1, stop)
        if right == -1:
            right = stop
        remaining[left:right] = b"\0" * (right - left)
        return left - start, right - start - 1, py

    try:
        # As before, replace the seed even if an alpha-bearing surface maps its
        # RGB target differently; ordinary Paint canvases are opaque RGB.
        remaining[y * width + x] = 1
        stack = [discover(x, y)]
        while stack:
            left, right, sy = stack.pop()
            pixels[left:right + 1, sy] = replacement
            for ny in (sy - 1, sy + 1):
                if not 0 <= ny < height:
                    continue
                start, stop = ny * width, ny * width + right + 1
                at = remaining.find(b"\1", start + left, stop)
                while at != -1:
                    run = discover(at - start, ny)
                    stack.append(run)
                    at = remaining.find(b"\1", start + run[1] + 1, stop)
    finally:
        pixels.close()



def _bucket_fill_small_format(surface: pygame.Surface, pos: Point, color: Color) -> None:
    width, height = surface.get_size()
    x, y = pos
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    target = surface.get_at((x, y))[:3]
    if target == color:
        return
    target_mapped = surface.map_rgb(target)
    replacement = surface.map_rgb(color)
    pixels: Optional[pygame.PixelArray] = None
    try:
        pixels = pygame.PixelArray(surface)
        lx = x
        while lx - 1 >= 0 and pixels[lx - 1, y] == target_mapped:
            lx -= 1
        rx = x
        while rx + 1 < width and pixels[rx + 1, y] == target_mapped:
            rx += 1
        stack = [(lx, rx, y)]
        while stack:
            lx, rx, sy = stack.pop()
            pixels[lx : rx + 1, sy] = replacement

            for ny in (sy - 1, sy + 1):
                if ny < 0 or ny >= height:
                    continue
                nx = lx
                while nx <= rx:
                    if pixels[nx, ny] != target_mapped:
                        nx += 1
                        continue
                    span_l = nx
                    while span_l - 1 >= 0 and pixels[span_l - 1, ny] == target_mapped:
                        span_l -= 1
                    span_r = nx
                    while span_r + 1 < width and pixels[span_r + 1, ny] == target_mapped:
                        span_r += 1
                    stack.append((span_l, span_r, ny))
                    nx = span_r + 1
    finally:
        if pixels is not None:
            del pixels


def _load_thumbnail(path: Path, size: Tuple[int, int]) -> Optional[pygame.Surface]:
    try:
        image = pygame.image.load(str(path)).convert_alpha()
    except (pygame.error, OSError):
        return None
    return pygame.transform.smoothscale(image, size)


def _recall_pixels(path: Path, size: Tuple[int, int]) -> Optional[bytes]:
    """Decode on the worker; pygame surfaces stay on the display thread."""
    try:
        with Image.open(path) as source:
            if source.width * source.height > 40_000_000:
                return None
            return source.convert("RGB").resize(size).tobytes()
    except DECODE_ERRORS:
        return None


def _load_canvas_image(path: Path, size: Tuple[int, int]) -> Optional[pygame.Surface]:
    try:
        with Image.open(path) as header:
            if header.width * header.height > MAX_PHOTO_PIXELS:
                return None
        image = pygame.image.load(str(path)).convert_alpha()
    except Exception:
        # Any unreadable save is preserved by the caller, never a crash loop.
        return None
    return pygame.transform.smoothscale(image, size)


def _scale_input_pos(
    pos: Point,
    source_size: Tuple[int, int],
    target_size: Tuple[int, int],
) -> Point:
    src_w, src_h = source_size
    tgt_w, tgt_h = target_size
    if src_w <= 0 or src_h <= 0 or tgt_w <= 0 or tgt_h <= 0:
        return pos
    if src_w == tgt_w and src_h == tgt_h:
        return pos
    x, y = float(pos[0]), float(pos[1])
    if not (0 <= x <= src_w and 0 <= y <= src_h):
        return pos
    scale_x = tgt_w / src_w
    scale_y = tgt_h / src_h
    return (
        int(round(x * scale_x)),
        int(round(y * scale_y)),
    )


class PaintApp:
    def __init__(
        self,
        *,
        screen: Optional[pygame.Surface] = None,
        screen_rect: Optional[pygame.Rect] = None,
        clock: Optional[pygame.time.Clock] = None,
    ) -> None:
        self.config = load_config()
        self.data_root = get_data_root(self.config)
        self.logger: RuntimeLogger = get_runtime_logger(self.data_root)
        dirs = ensure_directories(self.data_root)
        self.paint_dir = dirs["paint"]
        self._timing = PaintTiming.armed(self.data_root)

        if screen is None:
            self.screen, self.screen_rect = create_fullscreen_window()
        else:
            self.screen = screen
            self.screen_rect = screen_rect or screen.get_rect()
        self.clock = clock or pygame.time.Clock()

        self.margin = 16
        self.menu_pad = 10
        self.menu_gap = 10
        self.menu_bg = theme.PANEL
        self.tool_size = max(44, min(56, int(self.screen_rect.height * 0.06)))
        panel_width = self.tool_size * 2 + self.menu_gap + self.menu_pad * 2
        self.controls_rect = pygame.Rect(
            self.margin,
            self.margin,
            panel_width,
            self.screen_rect.height - 2 * self.margin,
        )
        self.canvas_rect = pygame.Rect(
            self.controls_rect.right + self.margin,
            self.margin,
            self.screen_rect.width - panel_width - 3 * self.margin,
            self.screen_rect.height - 2 * self.margin,
        )

        self._save_pending: Optional[tuple[int, Future]] = None
        self._exit_since: Optional[float] = None
        self.base_surface = pygame.Surface(self.canvas_rect.size)
        self.base_surface.fill((255, 255, 255))
        self.canvas_surface = self.base_surface.copy()
        self._canvas_revision = 0
        self._saved_revision = -1
        # False when the previous latest.png could not be preserved: never write over it.
        self._latest_writable = True
        try:
            for recovered in recover_orphans(self.paint_dir, suffix=".png", validate=_valid_png,
                                             recovered_dir=self.paint_dir):
                self.logger.warning(f"Preserved interrupted Paint save as {recovered.name}")
        except Exception:
            self._latest_writable = False
            self.logger.exception("Cannot classify interrupted Paint save; current saves disabled")
        latest = self.paint_dir / "latest.png"
        parked = retained.adopt("paint")
        if parked is not None:
            # Newer than disk: a previous visit's save had not finished.
            pixels, size = parked.state
            self.canvas_surface = pygame.transform.smoothscale(
                pygame.image.frombytes(pixels, size, "RGB").convert(), self.canvas_rect.size)
            self._latest_writable = self._latest_writable and not parked.write_disabled
            self._save_pending = None if parked.writer is None else (0, parked.writer)
            self.logger.info("Paint resumed parked work")
        elif latest.exists():
            restored = _load_canvas_image(latest, self.canvas_rect.size)
            if restored is not None:
                self.canvas_surface = restored
                self._saved_revision = 0
            else:
                # Keep damaged media for parent inspection before making a new save.
                try:
                    quarantine(latest)
                    self.logger.warning("Preserved unreadable paint save as corrupt media")
                except OSError:
                    self._latest_writable = False
                    self.logger.exception("Cannot preserve unreadable paint save; current saves disabled")

        self.palette = [tuple(color) for color in self.config.get("paint", {}).get("palette", [])]
        self.current_color: Color = self.palette[0] if self.palette else (0, 0, 0)

        self.current_tool = "fountain"
        self.size_values = self._scaled_size_values()
        self.current_size = self.size_values[1] if len(self.size_values) > 1 else self.size_values[0]
        self.undo_stack: List[pygame.Surface] = []
        self.redo_stack: List[pygame.Surface] = []
        self.current_stroke: Optional[Stroke] = None

        self.font = theme.ui_font(18)
        self.last_autosave = time.monotonic()
        self.autosave_interval = max(1, int(self.config.get("paint", {}).get("autosave_seconds", 10)))

        self.action_buttons: Dict[str, Button] = {}
        self.tool_buttons: Dict[str, Button] = {}
        self.size_buttons: Dict[int, Button] = {}
        self.palette_buttons: List[Button] = []
        self.recall_demo_path = Path(__file__).resolve().parents[3] / "assets" / "recall_demo_1024.png"
        self._build_ui()

        self.recall_open = False
        self.recall_items: List[RecallItem] = []
        self.recall_strip_rect = pygame.Rect(0, 0, 0, 0)
        self.recall_scroll_y = 0
        self.recall_max_scroll = 0
        self.recall_thumb_padding_x = 12
        self.recall_thumb_gap = 12
        self.recall_thumb_size = 0
        self.recall_strip_drag_last_y: Optional[int] = None
        self.recall_pressed_index: Optional[int] = None
        self.recall_drag_distance = 0
        self.pointer_down = False
        self.pointer_input = PointerInput()
        self._recall_worker: Optional[DaemonExecutor] = None
        self._recall_pending: Optional[tuple[int, Future]] = None
        self._recall_generation = 0
        self._save_worker: Optional[DaemonExecutor] = None
        self._save_failed = False
        self._transition_request = None
        self._transition_pending = None
        self._exit_requested = False
        # (archive, canvas digest) pairs whose canvas is already durably archived.
        self._known_archives: List[Tuple[Path, str]] = []
        self._recall_overlay = pygame.Surface(self.screen_rect.size, pygame.SRCALPHA)
        self._recall_overlay.fill((*theme.INK, 110))

    def _handle_resume(self, reason: str) -> None:
        self.logger.info(f"Paint resume handling triggered: {reason}")
        self.pointer_down = False
        if hasattr(self, "pointer_input"):
            self.pointer_input.reset()
        self.current_stroke = None
        self.recall_strip_drag_last_y = None
        self.recall_pressed_index = None
        self.recall_drag_distance = 0
        pointer_events = [
            pygame.MOUSEMOTION,
            pygame.MOUSEBUTTONDOWN,
            pygame.MOUSEBUTTONUP,
            pygame.MOUSEWHEEL,
        ]
        finger_down = getattr(pygame, "FINGERDOWN", None)
        finger_up = getattr(pygame, "FINGERUP", None)
        if finger_down is not None:
            pointer_events.append(finger_down)
        if finger_up is not None:
            pointer_events.append(finger_up)
        if FINGERMOTION is not None:
            pointer_events.append(FINGERMOTION)
        pygame.event.clear(pointer_events)

    def _should_reset_for_key(self, event: pygame.event.Event) -> bool:
        if event.type != pygame.KEYDOWN:
            return False
        if event.key == pygame.K_ESCAPE:
            return False
        if ignore_system_shortcut(event):
            return True
        if event.key in _MODIFIER_KEYS:
            return True
        return bool(event.mod & _NOISY_KEY_MODS)

    def _scaled_size_values(self) -> List[int]:
        base_sizes = [3, 6, 12]
        scale = min(self.screen_rect.width / 1366, self.screen_rect.height / 768)
        sizes = [max(1, int(round(size * scale))) for size in base_sizes]
        for idx in range(1, len(sizes)):
            if sizes[idx] <= sizes[idx - 1]:
                sizes[idx] = sizes[idx - 1] + 1
        return sizes

    def _build_ui(self) -> None:
        self.action_buttons.clear()
        self.tool_buttons.clear()
        self.size_buttons.clear()
        self.palette_buttons.clear()

        pad = self.menu_pad
        gap = self.menu_gap
        left = self.controls_rect.left + pad
        top = self.controls_rect.top + pad
        inner_w = self.controls_rect.width - pad * 2
        tool_size = min(self.tool_size, int((inner_w - gap) / 2))

        home_rect = theme.home_rect(self.screen_rect)
        self.action_buttons["home"] = Button(rect=home_rect, fill=theme.PAPER)

        tool_top = top
        icon_pad = 6
        tool_icons = [
            ("round", Path(__file__).resolve().parents[3] / "assets" / "icons" / "paint" / "brush_round" / "brush_round_256.png"),
            ("fountain", Path(__file__).resolve().parents[3] / "assets" / "icons" / "paint" / "fountain_pen" / "fountain_pen_256.png"),
            ("eraser", Path(__file__).resolve().parents[3] / "assets" / "icons" / "paint" / "eraser" / "eraser_256.png"),
            ("bucket", Path(__file__).resolve().parents[3] / "assets" / "icons" / "paint" / "paint_bucket" / "paint_bucket_256.png"),
        ]
        for idx, (tool, icon_path) in enumerate(tool_icons):
            row = idx // 2
            col = idx % 2
            rect = pygame.Rect(
                left + col * (tool_size + gap),
                tool_top + row * (tool_size + gap),
                tool_size,
                tool_size,
            )
            icon = _load_icon(
                icon_path,
                (max(1, tool_size - icon_pad), max(1, tool_size - icon_pad)),
                preserve_aspect=True,
            )
            self.tool_buttons[tool] = Button(rect=rect, image=icon, fill=theme.PAPER)

        size_gap = max(2, gap // 4)
        size_width = max(1, (inner_w - 2 * size_gap) // 3)
        size_height = max(24, int(tool_size * 1.1))
        size_left = left
        size_top = tool_top + 2 * tool_size + gap
        size_icons = [
            Path(__file__).resolve().parents[3] / "assets" / "icons" / "paint" / "line_thin" / "line_thin_256.png",
            Path(__file__).resolve().parents[3] / "assets" / "icons" / "paint" / "line_medium" / "line_medium_256.png",
            Path(__file__).resolve().parents[3] / "assets" / "icons" / "paint" / "line_fat" / "line_fat_256.png",
        ]
        for idx, (size, icon_path) in enumerate(zip(self.size_values, size_icons)):
            rect = pygame.Rect(
                size_left + idx * (size_width + size_gap),
                size_top,
                size_width,
                size_height,
            )
            icon = _load_icon(
                icon_path,
                (max(1, size_height - icon_pad), max(1, size_width - icon_pad)),
                preserve_aspect=False,
            )
            if icon is not None:
                icon = pygame.transform.rotate(icon, 90)
            self.size_buttons[size] = Button(rect=rect, image=icon, fill=theme.PAPER)

        size_bottom = size_top + size_height

        action_h = self.font.get_height() + 16
        action_gap = gap
        recall_new_gap = 2
        recall_h = min(
            inner_w,
            max(1, int(inner_w * (self.canvas_rect.height / self.canvas_rect.width))),
        )
        bottom_total = recall_h + 2 * action_h + recall_new_gap + action_gap
        bottom_top = self.controls_rect.bottom - pad - bottom_total
        bottom_left = left

        recall_rect = pygame.Rect(bottom_left, bottom_top, inner_w, recall_h)
        self.action_buttons["recall"] = Button(rect=recall_rect, label="Recall", fill=theme.PAPER)

        new_rect = pygame.Rect(
            bottom_left,
            recall_rect.bottom + recall_new_gap,
            inner_w,
            action_h,
        )
        self.action_buttons["new"] = Button(rect=new_rect, label="New", fill=theme.PAPER)

        half_w = max(1, (inner_w - action_gap) // 2)
        undo_rect = pygame.Rect(
            bottom_left,
            new_rect.bottom + action_gap,
            half_w,
            action_h,
        )
        self.action_buttons["undo"] = Button(rect=undo_rect, label="Undo", fill=theme.PAPER)

        redo_rect = pygame.Rect(
            bottom_left + half_w + action_gap,
            new_rect.bottom + action_gap,
            half_w,
            action_h,
        )
        self.action_buttons["redo"] = Button(rect=redo_rect, label="Redo", fill=theme.PAPER)

        palette_gap = max(4, gap // 2)
        palette_top = size_bottom + palette_gap + 4
        palette_bottom = bottom_top - 4
        if palette_bottom < palette_top:
            palette_bottom = palette_top
        palette_rect = pygame.Rect(left, palette_top, inner_w, palette_bottom - palette_top)

        swatch_gap = 6
        # Use additional columns instead of extending below the allotted area.
        columns = 1 if len(self.palette) * 30 + max(0, len(self.palette) - 1) * swatch_gap <= palette_rect.height else 2
        rows = max(1, math.ceil(len(self.palette) / columns))
        swatch_height = max(1, (palette_rect.height - swatch_gap * (rows - 1)) // rows)
        swatch_width = max(1, (palette_rect.width - swatch_gap * (columns - 1)) // columns)
        for idx, color in enumerate(self.palette):
            rect = pygame.Rect(
                palette_rect.left + (idx % columns) * (swatch_width + swatch_gap),
                palette_rect.top + (idx // columns) * (swatch_height + swatch_gap),
                swatch_width,
                swatch_height,
            )
            self.palette_buttons.append(Button(rect=rect, fill=color))

        self._update_thumbnail_button()

    def _event_pos(self, event: pygame.event.Event) -> Optional[Point]:
        raw_pos = pointer_event_pos(event, self.screen_rect)
        if raw_pos is None:
            return None
        window_size = pygame.display.get_window_size()
        is_touch_emulated_mouse = bool(getattr(event, "touch", False))
        is_finger_event = event.type in FINGER_EVENTS
        if FINGERMOTION is not None:
            is_finger_event = is_finger_event or event.type == FINGERMOTION
        if window_size == self.screen_rect.size or is_finger_event or is_touch_emulated_mouse:
            return raw_pos
        scaled_pos = _scale_input_pos(raw_pos, window_size, self.screen_rect.size)
        return self._resolve_pointer_pos(raw_pos, scaled_pos)

    def _pointer_target(self, pos: Point) -> Optional[Tuple[int, str]]:
        if self.recall_open:
            if self._recall_index_at_pos(pos) is not None:
                return (0, "recall-item")
            if self.recall_strip_rect.collidepoint(pos):
                return (1, "recall-strip")
            return None

        button_order = (
            ("home", self.action_buttons.get("home")),
            ("new", self.action_buttons.get("new")),
            ("undo", self.action_buttons.get("undo")),
            ("redo", self.action_buttons.get("redo")),
            ("recall", self.action_buttons.get("recall")),
        )
        for name, button in button_order:
            if button is not None and button.hit(pos):
                return (0, name)

        for tool, button in self.tool_buttons.items():
            if button.hit(pos):
                return (1, f"tool:{tool}")

        for size, button in self.size_buttons.items():
            if button.hit(pos):
                return (1, f"size:{size}")

        for idx, button in enumerate(self.palette_buttons):
            if button.hit(pos):
                return (1, f"palette:{idx}")

        if self.canvas_rect.collidepoint(pos):
            return (2, "canvas")
        return None

    def _resolve_pointer_pos(self, raw_pos: Point, scaled_pos: Point) -> Point:
        if raw_pos == scaled_pos:
            return raw_pos

        raw_target = self._pointer_target(raw_pos)
        scaled_target = self._pointer_target(scaled_pos)
        if raw_target is None:
            return scaled_pos
        if scaled_target is None:
            return raw_pos
        if raw_target[0] != scaled_target[0]:
            return raw_pos if raw_target[0] < scaled_target[0] else scaled_pos
        if raw_target[1] == scaled_target[1] == "canvas":
            return scaled_pos
        if self.current_stroke is not None and scaled_target[1] == "canvas":
            return scaled_pos
        return raw_pos


    def _push_undo(self) -> None:
        self.undo_stack.append(self.canvas_surface.copy())
        if len(self.undo_stack) > UNDO_MAX_DEPTH:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _undo(self) -> None:
        if self.undo_stack:
            self.redo_stack.append(self.canvas_surface.copy())
            self.canvas_surface = self.undo_stack.pop()
            self._mark_canvas_changed()

    def _redo(self) -> None:
        if self.redo_stack:
            self.undo_stack.append(self.canvas_surface.copy())
            self.canvas_surface = self.redo_stack.pop()
            self._mark_canvas_changed()

    def _mark_canvas_changed(self) -> None:
        self._canvas_revision = getattr(self, "_canvas_revision", 0) + 1

    def _current_draw_color(self) -> Color:
        if self.current_tool == "eraser":
            return (255, 255, 255)
        return self.current_color

    def _handle_pointer_down(self, pos: Point, *, defer_saves: bool = False) -> bool:
        if defer_saves:
            if self.action_buttons["home"].hit(pos):
                self._save_failed = False
                self._exit_requested = True
                self.current_stroke = None
                return False
            if self._transition_request is not None or self._transition_pending is not None or self._exit_requested:
                return False
            if self.action_buttons["new"].hit(pos):
                self._begin_transition("new")
                return False
            if self.action_buttons["recall"].hit(pos):
                self._begin_transition("open")
                return False
        if self.action_buttons["home"].hit(pos):
            return self._autosave_latest()

        if self.canvas_rect.collidepoint(pos):
            local_pos = (pos[0] - self.canvas_rect.left, pos[1] - self.canvas_rect.top)
            if self.current_tool == "bucket":
                self._push_undo()
                _bucket_fill(self.canvas_surface, local_pos, self.current_color)
                self._mark_canvas_changed()
                return False
            self._push_undo()
            self.current_stroke = Stroke(
                tool=self.current_tool,
                size=self.current_size,
                color=self._current_draw_color(),
                points=[local_pos],
            )
            _draw_stamp(self.canvas_surface, self.current_tool, self.current_size,
                        self._current_draw_color(), local_pos)
            self._mark_canvas_changed()
            return False

        for tool, button in self.tool_buttons.items():
            if button.hit(pos):
                self.current_tool = tool
                return False

        for size, button in self.size_buttons.items():
            if button.hit(pos):
                self.current_size = size
                return False

        for idx, button in enumerate(self.palette_buttons):
            if button.hit(pos):
                self.current_color = self.palette[idx]
                return False

        if self.action_buttons["undo"].hit(pos):
            self._undo()
            return False
        if self.action_buttons["redo"].hit(pos):
            self._redo()
            return False
        if self.action_buttons["new"].hit(pos):
            if self._archive_current():
                self._reset_canvas()
                self._autosave_latest()
            return False
        if self.action_buttons["recall"].hit(pos):
            self._open_recall()
            return False
        return False

    def _handle_pointer_move(self, pos: Point) -> None:
        if not self.current_stroke:
            return
        self._mark_canvas_changed()
        local_pos = (pos[0] - self.canvas_rect.left, pos[1] - self.canvas_rect.top)
        last_point = self.current_stroke.points[-1]
        if self.current_stroke.tool == "fountain":
            # Densify fountain updates to avoid visible segment artifacts.
            distance = max(1.0, pygame.math.Vector2(local_pos).distance_to(last_point))
            steps = max(1, int(distance / FOUNTAIN_DENSITY))
            prev = last_point
            width = self.current_stroke.fountain_width
            for idx in range(1, steps + 1):
                t = idx / steps
                next_point = (
                    int(last_point[0] + (local_pos[0] - last_point[0]) * t),
                    int(last_point[1] + (local_pos[1] - last_point[1]) * t),
                )
                target_width = float(_fountain_width_for_direction(self.current_stroke.size, prev, next_point))
                if width <= 0:
                    width = target_width
                smoothed_width = width + (target_width - width) * FOUNTAIN_SMOOTHING
                _draw_fountain_segment(
                    self.canvas_surface,
                    self.current_stroke.color,
                    prev,
                    next_point,
                    width,
                    smoothed_width,
                    start_cap=idx == 1,
                )
                width = smoothed_width
                self.current_stroke.points[:] = [next_point]
                prev = next_point
            self.current_stroke.fountain_width = width
            return
        self.current_stroke.points[:] = [local_pos]
        _draw_segment(self.canvas_surface, self.current_stroke, last_point, local_pos)

    def _handle_pointer_up(self) -> None:
        self.current_stroke = None

    def _update_thumbnail_button(self) -> None:
        size = self.action_buttons["recall"].rect.size
        icon_size = (max(1, size[0] - 6), max(1, size[1] - 6))
        self.action_buttons["recall"].image = pygame.transform.smoothscale(self.canvas_surface, icon_size)

    def _autosave_latest(self, timeout: Optional[float] = None) -> bool:
        # Synchronous final/direct save API, serialized after an older snapshot.
        # Interactive Home/New/Recall/control paths poll the writer instead.
        # With a timeout (shutdown), the write runs on the worker and is bounded.
        self._finish_pending_save(wait=True, timeout=timeout)
        if self._save_pending is not None:
            return False
        if self._saved_revision == self._canvas_revision:
            return True
        if not self._latest_writable:
            return False
        if timeout is not None:
            self._request_autosave()
            self._finish_pending_save(wait=True, timeout=timeout)
            return self._saved_revision == self._canvas_revision
        latest_path = self.paint_dir / "latest.png"
        try:
            _save_pixels_atomic(_canvas_pixels(self.canvas_surface), self.canvas_surface.get_size(), latest_path)
        except Exception:
            self.logger.exception("Paint autosave failed")
            return False
        self._saved_revision = self._canvas_revision
        self._save_failed = False
        self.logger.info("Paint current canvas committed")
        return True

    def _finish_pending_save(self, *, wait: bool = False, timeout: Optional[float] = None) -> None:
        if self._save_pending is None:
            return
        revision, future = self._save_pending
        if wait:
            wait_futures([future], timeout=timeout)
        if not future.done():
            return
        self._save_pending = None
        try:
            future.result()
        except Exception:
            self._save_failed = True
            self.logger.exception("Paint background autosave failed; canvas remains dirty")
        else:
            self._save_failed = False
            self._saved_revision = revision
            self.logger.info("Paint current canvas committed")

    def _request_autosave(self) -> None:
        self._finish_pending_save()
        if self._save_pending is not None or self._saved_revision == self._canvas_revision:
            return
        if not self._latest_writable:
            return
        if self._save_worker is None:
            self._save_worker = DaemonExecutor("paint-save")
        self._save_failed = False
        # Immutable copy: the child can continue drawing while PNG/fsync runs.
        pixels = _canvas_pixels(self.canvas_surface)
        future = self._save_worker.submit(_save_pixels_atomic, pixels, self.canvas_surface.get_size(),
                                          self.paint_dir / "latest.png")
        self._save_pending = (self._canvas_revision, future)

    def _save_for_control(self):
        self._finish_pending_save()
        if self._saved_revision != self._canvas_revision and not self._latest_writable:
            return False
        if self._save_failed:
            self._save_failed = False  # Consume one failure; a new explicit request can retry.
            return False
        if self._saved_revision == self._canvas_revision:
            return True
        self._request_autosave()
        return control.SAVE_PENDING

    def _begin_transition(self, kind: str, source: Optional[Path] = None) -> None:
        if self._transition_request is not None or self._transition_pending is not None or self._exit_requested:
            return
        self.current_stroke = None
        self.pointer_down = False
        self._transition_request = (kind, source)

    def _service_transition(self) -> None:
        self._finish_pending_save()
        if self._save_pending is not None:
            return
        if self._transition_pending is not None:
            kind, future, source = self._transition_pending
            if not future.done():
                return
            self._transition_pending = None
            try:
                result = future.result()
            except Exception:
                self.logger.exception("Paint transition failed; preserving current canvas")
                return
            if result.published is not None:
                self._remember_archive(result.published, result.digest)
            if kind == "new":
                self._update_thumbnail_button()
                self._reset_canvas()
            else:
                original_size, rgba = result.loaded
                decoded = pygame.image.frombytes(rgba, original_size, "RGBA").convert_alpha()
                self.canvas_surface = pygame.transform.smoothscale(decoded, self.canvas_rect.size)
                self._mark_canvas_changed()
                self.undo_stack = []
                self.redo_stack = []
                self._update_thumbnail_button()
                self.recall_open = False
                if source is not None:
                    self._remember_archive(source, self._canvas_digest())
            # Archive was durably committed before the working canvas changed.
            self._request_autosave()
        if self._transition_request is None:
            return
        kind, source = self._transition_request
        if kind == "open":
            if self._saved_revision != self._canvas_revision:
                if self._save_failed:
                    self._transition_request = None
                    return
                self._request_autosave()
                return
            self._transition_request = None
            self._open_recall()  # Already saved; no encoding/fsync on this path.
            return
        self._transition_request = None
        if self._save_worker is None:
            self._save_worker = DaemonExecutor("paint-save")
        pixels = _canvas_pixels(self.canvas_surface)
        limit = _coerce_archive_limit(self.config.get("paint", {}).get("max_archives", MAX_ARCHIVES), MAX_ARCHIVES)
        self._transition_pending = (kind, self._save_worker.submit(
            _archive_pixels, pixels, self.canvas_rect.size, self.paint_dir, limit, source,
            tuple(self._known_archives)), source)

    def _poll_exit(self) -> bool:
        if not self._exit_requested:
            return False
        if self._exit_since is None:
            self._exit_since = time.monotonic()
        waiting = time.monotonic() - self._exit_since < EXIT_GRACE_SECONDS
        if self._transition_request is not None or self._transition_pending is not None:
            if waiting:
                return False
            self._abandon_transition()
        self._finish_pending_save()
        if self._saved_revision == self._canvas_revision:
            return True
        if self._latest_writable and not self._save_failed and waiting:
            self._request_autosave()
            return False
        # Home never waits on storage: the launcher keeps and keeps saving this canvas.
        self._park_unsaved()
        return True

    def _abandon_transition(self) -> None:
        # Home wins over a stalled New/Recall: the current canvas is parked unchanged;
        # a late archive still lands on disk but can no longer alter any document.
        if self._transition_pending is not None:
            self.logger.warning("Paint New/Recall still saving at exit; current canvas kept unchanged")
        self._transition_request = None
        self._transition_pending = None

    def _park_unsaved(self) -> None:
        pixels, size = _canvas_pixels(self.canvas_surface), self.canvas_surface.get_size()
        retained.park(retained.ParkedWork(
            "paint", self.paint_dir / "latest.png", lambda: _encode_png(pixels, size), (pixels, size),
            prior=None if self._save_pending is None else self._save_pending[1],
            write_disabled=not self._latest_writable))
        self._save_pending = None
        self._saved_revision = self._canvas_revision  # Ownership moved to the launcher.
        self.logger.warning("Paint save unfinished at exit; work kept in memory and saving continues")

    def _canvas_digest(self) -> str:
        return _pixels_digest(_canvas_pixels(self.canvas_surface))

    def _remember_archive(self, path: Path, digest: str) -> None:
        self._known_archives = [*self._known_archives[-(KNOWN_ARCHIVES - 1):], (path, digest)]

    def _archive_current(self) -> bool:
        pixels = _canvas_pixels(self.canvas_surface)
        size = self.canvas_surface.get_size()
        digest = _pixels_digest(pixels)
        if _archive_duplicate(pixels, size, self.paint_dir, tuple(self._known_archives), digest):
            return True  # Already preserved (or blank): nothing new to archive.
        if not self._archive_capacity_available():
            return False
        try:
            published = publish_new_bytes(self.paint_dir / _archive_name(), _encode_png(pixels, size))
        except Exception:
            self.logger.exception("Paint archive write failed")
            return False
        self._remember_archive(published, digest)
        self._update_thumbnail_button()
        return True

    def _archive_capacity_available(self) -> bool:
        max_archives = _coerce_archive_limit(
            self.config.get("paint", {}).get("max_archives", MAX_ARCHIVES),
            MAX_ARCHIVES,
        )
        archives = self._recall_archives()
        if len(archives) >= max_archives:
            self.logger.warning("Paint archive capacity reached; preserving current and archived work")
            return False
        try:
            # PNG worst case is near raw RGB plus compression overhead.
            estimate = self.canvas_surface.get_width() * self.canvas_surface.get_height() * 4 + 65536
            if not has_archive_reserve(self.paint_dir, estimate):
                self.logger.warning("Paint archive refused to preserve free space for current saves")
                return False
        except OSError:
            self.logger.exception("Cannot check free space for Paint archive")
            return False
        return True

    def _recall_archives(self) -> List[Path]:
        return [path for path in _list_archives(self.paint_dir) if _is_paint_archive(path)]

    def _reset_canvas(self) -> None:
        self.base_surface.fill((255, 255, 255))
        self.canvas_surface = self.base_surface.copy()
        self.undo_stack = []
        self.redo_stack = []
        self._mark_canvas_changed()

    def _open_recall(self) -> None:
        # Persist current canvas before showing recall so latest work appears immediately.
        self._autosave_latest()
        self._update_thumbnail_button()
        self.recall_strip_rect = self.controls_rect.copy()
        self.recall_thumb_size = max(1, self.recall_strip_rect.width - (self.recall_thumb_padding_x * 2))
        self.recall_items = [
            RecallItem(thumb=pygame.transform.smoothscale(self.canvas_surface, (self.recall_thumb_size, self.recall_thumb_size)))
        ]
        archives = self._recall_archives()
        if not archives and self.recall_demo_path.exists():
            archives = [self.recall_demo_path]
        self._recall_generation += 1
        for path in archives:
            self.recall_items.append(RecallItem(thumb=None, source=path))
        self.recall_scroll_y = 0
        self.recall_strip_drag_last_y = None
        self.recall_pressed_index = None
        self.recall_drag_distance = 0
        self.recall_max_scroll = self._recall_max_scroll()
        self.recall_open = True

    def _pump_recall_thumbnail(self) -> None:
        if self._recall_pending is not None:
            generation, future = self._recall_pending
            if not future.done():
                return
            self._recall_pending = None
            index, pixels = future.result()
            if generation == self._recall_generation and index < len(self.recall_items):
                item = self.recall_items[index]
                size = (self.recall_thumb_size, self.recall_thumb_size)
                item.thumb = pygame.image.frombytes(pixels, size, "RGB") if pixels else pygame.Surface(size)
        if not self.recall_open:
            return
        for index, item in enumerate(self.recall_items):
            if item.thumb is not None or item.source is None:
                continue
            if not self._recall_item_rect(index).colliderect(self.recall_strip_rect):
                continue
            if self._recall_worker is None:
                self._recall_worker = DaemonExecutor("paint-recall")
            def decode(index=index, path=item.source, size=self.recall_thumb_size):
                return index, _recall_pixels(path, (size, size))
            self._recall_pending = (self._recall_generation, self._recall_worker.submit(decode))
            break

    def _recall_max_scroll(self) -> int:
        total_height = len(self.recall_items) * (self.recall_thumb_size + self.recall_thumb_gap) + self.recall_thumb_gap
        return max(0, total_height - self.recall_strip_rect.height)

    def _scroll_recall(self, delta: int) -> None:
        self.recall_scroll_y = max(0, min(self.recall_max_scroll, self.recall_scroll_y + delta))

    def _recall_item_rect(self, index: int) -> pygame.Rect:
        y = self.recall_thumb_gap - self.recall_scroll_y + index * (self.recall_thumb_size + self.recall_thumb_gap)
        return pygame.Rect(
            self.recall_strip_rect.left + self.recall_thumb_padding_x,
            self.recall_strip_rect.top + y,
            self.recall_thumb_size,
            self.recall_thumb_size,
        )

    def _handle_recall_selection(self, item: RecallItem, *, defer_saves: bool = False) -> None:
        if item.source is None:
            self.recall_open = False
            return
        if defer_saves:
            self._begin_transition("recall", item.source)
            return
        loaded = _load_canvas_image(item.source, self.canvas_rect.size)
        if loaded is None:
            return
        if not self._archive_current():
            return
        self.canvas_surface = loaded.copy()
        self._mark_canvas_changed()
        self.undo_stack = []
        self.redo_stack = []
        self._remember_archive(item.source, self._canvas_digest())
        # Always promote selected archive into latest working copy.
        self._autosave_latest()
        self.last_autosave = time.monotonic()
        self._update_thumbnail_button()
        self.recall_open = False

    def _recall_index_at_pos(self, pos: Point) -> Optional[int]:
        for idx, _ in enumerate(self.recall_items):
            if self._recall_item_rect(idx).collidepoint(pos):
                return idx
        return None

    def _handle_recall_event(self, event: pygame.event.Event) -> None:
        if is_primary_pointer_event(event, is_down=True):
            if self.pointer_down:
                # Ignore duplicate emulated pointer-down events from touch stacks.
                return
            pos = self._event_pos(event)
            if pos is None:
                return
            self.pointer_down = True
            if not self.recall_strip_rect.collidepoint(pos):
                self.recall_open = False
                self.pointer_down = False
                self.recall_strip_drag_last_y = None
                self.recall_pressed_index = None
                self.recall_drag_distance = 0
                return
            self.recall_strip_drag_last_y = pos[1]
            self.recall_pressed_index = self._recall_index_at_pos(pos)
            self.recall_drag_distance = 0
        if is_primary_pointer_event(event, is_down=False):
            if not self.pointer_down:
                # Ignore duplicate emulated pointer-up events.
                return
            self.pointer_down = False
            pos = self._event_pos(event)
            if (
                pos is not None
                and self.recall_drag_distance < DRAG_THRESHOLD
                and self.recall_pressed_index is not None
                and self._recall_index_at_pos(pos) == self.recall_pressed_index
            ):
                self._handle_recall_selection(self.recall_items[self.recall_pressed_index], defer_saves=True)
            self.recall_strip_drag_last_y = None
            self.recall_pressed_index = None
            self.recall_drag_distance = 0
        if event.type == pygame.MOUSEWHEEL:
            if self.recall_strip_rect.collidepoint(pygame.mouse.get_pos()):
                self._scroll_recall(-event.y * SCROLL_STEP)
        if event.type == pygame.MOUSEBUTTONDOWN and getattr(event, "button", None) in {4, 5}:
            pos = self._event_pos(event)
            if pos and self.recall_strip_rect.collidepoint(pos):
                self._scroll_recall(-SCROLL_STEP if event.button == 4 else SCROLL_STEP)
        if event.type == pygame.MOUSEMOTION and self.recall_strip_drag_last_y is not None:
            dy = event.pos[1] - self.recall_strip_drag_last_y
            self._scroll_recall(-dy)
            self.recall_drag_distance += abs(dy)
            self.recall_strip_drag_last_y = event.pos[1]
        if FINGERMOTION is not None and event.type == FINGERMOTION and self.pointer_down:
            current_y = int(event.y * self.screen_rect.height)
            if self.recall_strip_drag_last_y is None:
                self.recall_strip_drag_last_y = current_y
            dy = current_y - self.recall_strip_drag_last_y
            self._scroll_recall(-dy)
            self.recall_drag_distance += abs(dy)
            self.recall_strip_drag_last_y = current_y

    def _draw_recall_overlay(self) -> None:
        self.screen.blit(self._recall_overlay, (0, 0))
        theme.card(self.screen, self.recall_strip_rect, fill=theme.PANEL)
        for idx, item in enumerate(self.recall_items):
            rect = self._recall_item_rect(idx)
            if rect.bottom < self.recall_strip_rect.top or rect.top > self.recall_strip_rect.bottom:
                continue
            if item.thumb is not None:
                self.screen.blit(item.thumb, rect)
            border_color = theme.ACCENT if idx == 0 else theme.BORDER
            pygame.draw.rect(self.screen, border_color, rect, width=3 if idx == 0 else 2)

    def _draw_controls(self, surface: pygame.Surface) -> None:
        surface.fill(theme.BACKGROUND)
        pygame.draw.rect(surface, self.menu_bg, self.controls_rect, border_radius=18)

        for tool, button in self.tool_buttons.items():
            button.draw(surface, selected=tool == self.current_tool)

        for size, button in self.size_buttons.items():
            button.draw(surface, selected=size == self.current_size)

        for idx, button in enumerate(self.palette_buttons):
            color = self.palette[idx]
            if color == self.current_color:
                pygame.draw.rect(surface, theme.PAPER, button.rect, border_radius=8)
                pygame.draw.rect(surface, color, button.rect.inflate(-8, -8), border_radius=5)
                theme.selection(surface, button.rect, radius=8)
            else:
                button.draw(surface)

        for key, button in self.action_buttons.items():
            if key == "home":
                continue  # Home overlays the canvas; draw it after the canvas blit.
            if key in {"new", "undo", "redo"} or (key == "recall" and button.image is None):
                button.draw(surface, self.font)
            else:
                button.draw(surface)

    def _render(self) -> None:
        timing = getattr(self, "_timing", None)
        render_started = time.perf_counter() if timing else 0.
        # Controls are static during a stroke. Cache their pixels, not input or
        # canvas samples; every accepted movement still reaches the old renderer.
        key = (self.screen.get_size(), self.current_tool, self.current_size,
               self.current_color, self.action_buttons["recall"].image)
        if getattr(self, "_controls_cache_key", None) != key:
            surface = self.screen.copy()
            self._draw_controls(surface)
            self._controls_cache = surface.subsurface(self.controls_rect).copy()
            self._controls_cache_key = key
        self.screen.fill(theme.BACKGROUND)
        self.screen.blit(self._controls_cache, self.controls_rect.topleft)
        self.screen.blit(self.canvas_surface, self.canvas_rect.topleft)
        pygame.draw.rect(self.screen, theme.BORDER, self.canvas_rect, width=1)
        draw_home_button(self.screen, self.action_buttons["home"].rect)

        if self.recall_open:
            self._draw_recall_overlay()

        control.before_flip(self.screen, self._save_for_control)
        flip_started = time.perf_counter() if timing else 0.
        pygame.display.flip()
        if timing:
            timing.observe("render_work", flip_started - render_started)
            timing.observe("display_flip", time.perf_counter() - flip_started)

    def run(self, *, quit_on_exit: bool = True) -> None:
        try:
            self._run()
        finally:
            # TERM/scene exit serialize behind an in-flight archive. Never let
            # an older periodic snapshot overwrite the final current canvas.
            if self._transition_pending is not None:
                try:
                    self._transition_pending[1].result(timeout=SHUTDOWN_WAIT_SECONDS)
                except Exception:
                    self.logger.exception("Paint archive did not finish at shutdown")
                    self._abandon_transition()
                else:
                    self._service_transition()
            self._transition_request = None
            if not self._autosave_latest(timeout=SHUTDOWN_WAIT_SECONDS):
                self._park_unsaved()
            if self._recall_worker is not None:
                self._recall_worker.shutdown(wait=False, cancel_futures=True)
            if self._save_worker is not None:
                self._save_worker.shutdown(wait=False, cancel_futures=True)
            if quit_on_exit:
                pygame.quit()

    def _run(self) -> None:
        running = True
        if getattr(self, "_timing", None):
            self._timing.context = {
                "screen_size": self.screen.get_size(), "canvas_size": self.canvas_surface.get_size(),
                "canvas_bytes_per_pixel": self.canvas_surface.get_bytesize(),
                "canvas_flags": self.canvas_surface.get_flags(),
                "sdl_version": pygame.get_sdl_version(), "video_driver": pygame.display.get_driver(),
                "compositor_hint": os.environ.get("WLR_RENDERER"),
                "sdl_renderer_hint": os.environ.get("SDL_RENDER_DRIVER"),
            }
        self._render()
        last_frame_time = time.monotonic()
        while running and not health.stopping():
            timing = getattr(self, "_timing", None)
            if timing:
                timing.frame()
            events_started = time.perf_counter() if timing else 0.
            now = time.monotonic()
            if now - last_frame_time > 2.0:
                self._handle_resume("frame-time gap")
            last_frame_time = now
            discard_input = False
            if timing:
                timing.state(self.current_tool)
                pump_started = time.perf_counter()
                pygame.event.pump()
                timing.observe('event_pump', time.perf_counter() - pump_started)
                timing.sample_touch_queue()
                events = pygame.event.get(pump=False)
            else:
                events = pygame.event.get()
            if timing:
                timing.count("events_received", len(events))
            for event in events:
                if discard_input and event.type != pygame.QUIT:
                    continue
                if event.type in _INPUT_RESET_EVENTS:
                    self._handle_resume("window/input state event")
                    discard_input = True
                    continue
                if self._should_reset_for_key(event):
                    self._handle_resume("ignored keyboard shortcut")
                    discard_input = True
                    continue
                accepted = self.pointer_input.accept(event)
                if timing and (event.type in FINGER_EVENTS or event.type in {
                        pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION}):
                    timing.count("pointer_accepted" if accepted else "pointer_rejected")
                if not accepted:
                    continue
                if event.type == pygame.QUIT:
                    self._exit_requested = True
                if self._transition_request is not None or self._transition_pending is not None or self._exit_requested:
                    if is_primary_pointer_event(event, is_down=False):
                        self.pointer_down = False
                        self._handle_pointer_up()
                    if is_primary_pointer_event(event, is_down=True):
                        pos = self._event_pos(event)
                        if pos is not None and self.action_buttons["home"].hit(pos):
                            self._exit_requested = True
                    continue
                if self.recall_open:
                    self._handle_recall_event(event)
                    continue
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if escape_exits():
                        self._exit_requested = True
                elif is_primary_pointer_event(event, is_down=True):
                    pos = self._event_pos(event)
                    if pos is None:
                        continue
                    self.pointer_down = True
                    if self._handle_pointer_down(pos, defer_saves=True):
                        running = False
                        break
                elif event.type == pygame.MOUSEMOTION or (FINGERMOTION is not None and event.type == FINGERMOTION):
                    if event.type == pygame.MOUSEMOTION:
                        if not (self.pointer_down or event.buttons[0]):
                            continue
                    elif not self.pointer_down:
                        continue
                    pos = self._event_pos(event)
                    if pos is None:
                        continue
                    self._handle_pointer_move(pos)
                elif is_primary_pointer_event(event, is_down=False):
                    self.pointer_down = False
                    self._handle_pointer_up()

            if timing:
                timing.state(self.current_tool)
                timing.observe("event_batch", time.perf_counter() - events_started)
            now = time.monotonic()
            if now - self.last_autosave >= self.autosave_interval:
                save_started = time.perf_counter() if timing else 0.
                self._request_autosave()
                if timing:
                    timing.observe("autosave_snapshot", time.perf_counter() - save_started)
                self.last_autosave = now

            self._service_transition()
            if self._poll_exit():
                break
            self._pump_recall_thumbnail()
            self._render()
            health.frame_complete()
            tick_started = time.perf_counter() if timing else 0.
            self.clock.tick(60)
            if timing:
                timing.observe("clock_tick", time.perf_counter() - tick_started)


def main() -> None:
    try:
        PaintApp().run(quit_on_exit=True)
        retained.flush(5.0)
    except Exception:
        logger = get_runtime_logger(get_data_root(load_config()))
        logger.exception("Paint app crashed in main()")
        pygame.quit()


def run_embedded(screen: pygame.Surface, screen_rect: pygame.Rect, clock: pygame.time.Clock) -> None:
    PaintApp(screen=screen, screen_rect=screen_rect, clock=clock).run(quit_on_exit=False)


if __name__ == "__main__":
    main()
