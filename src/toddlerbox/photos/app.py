from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import time
from typing import List, Optional, Tuple

import pygame
from toddlerbox.runtime import health
try:
    from PIL import Image, ImageOps
except Exception:
    Image = None

FINGERMOTION = getattr(pygame, "FINGERMOTION", None)

# --- Tuning constants ---
DRAG_THRESHOLD = 10
SWIPE_THRESHOLD = 80
SCROLL_STEP = 40
MAX_PHOTO_PIXELS = 40_000_000

from toddlerbox.config import load_config
from toddlerbox.paths import ensure_directories, get_data_root
from toddlerbox.runtime import RuntimeLogger, get_runtime_logger
from toddlerbox.ui import theme
from toddlerbox.ui.common import (
    Button,
    PointerInput,
    create_fullscreen_window,
    draw_home_button,
    ignore_system_shortcut,
    is_primary_pointer_event,
    pointer_event_pos,
)

WINDOW_FOCUS_GAINED = getattr(pygame, "WINDOWFOCUSGAINED", None)
WINDOW_FOCUS_LOST = getattr(pygame, "WINDOWFOCUSLOST", None)
WINDOW_RESTORED = getattr(pygame, "WINDOWRESTORED", None)
WINDOW_SIZE_CHANGED = getattr(pygame, "WINDOWSIZECHANGED", None)
APP_DID_ENTER_FOREGROUND = getattr(pygame, "APP_DIDENTERFOREGROUND", None)
APP_DID_ENTER_BACKGROUND = getattr(pygame, "APP_DIDENTERBACKGROUND", None)

_INPUT_RESET_EVENTS = {
    event
    for event in (
        WINDOW_FOCUS_GAINED,
        WINDOW_FOCUS_LOST,
        WINDOW_RESTORED,
        WINDOW_SIZE_CHANGED,
        APP_DID_ENTER_FOREGROUND,
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


@dataclass
class PhotoItem:
    path: Path
    thumb: Optional[pygame.Surface] = None


_EXIF_DATE_TAGS = (36867, 36868, 306)


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".gif"}


def _thumb_name(path: Path) -> str:
    suffix = path.suffix.lower().replace(".", "")
    return f"{path.stem}_{suffix}.png"


def _decode_photo(path: Path, size: Optional[Tuple[int, int]] = None, upscale: bool = False) -> tuple[bytes, Tuple[int, int]]:
    """Prepare immutable, oriented pixels without calling pygame in the worker."""
    with Image.open(path) as image:
        # PNG/BMP orientation and conversion can allocate full-resolution copies.
        # Check the header before decoding, even when the requested result is tiny.
        if image.width * image.height > MAX_PHOTO_PIXELS:
            raise ValueError(f"Photo exceeds supported {MAX_PHOTO_PIXELS}-pixel limit: {path}")
        if size is not None:
            # JPEG decoders can downsample before allocating the full image.
            image.draft("RGB", (max(size), max(size)))
        image = ImageOps.exif_transpose(image)
        if size is not None:
            if upscale:
                image = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
            else:
                image.thumbnail(size, Image.Resampling.LANCZOS)
        image = image.convert("RGBA")
        return image.tobytes(), image.size


def _surface_from_pixels(pixels: tuple[bytes, Tuple[int, int]]) -> pygame.Surface:
    data, size = pixels
    return pygame.image.frombytes(data, size, "RGBA").convert_alpha()


def _load_photo_surface(path: Path, *, for_thumbnail: bool = False) -> pygame.Surface:
    return _surface_from_pixels(_decode_photo(path))


def _prepare_thumbnail(path: Path, thumb_path: Path, size: Tuple[int, int]):
    try:
        if thumb_path.stat().st_mtime_ns >= path.stat().st_mtime_ns:
            return _decode_photo(thumb_path, size)
    except (OSError, ValueError):
        pass
    pixels = _decode_photo(path, size)
    try:
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.frombytes("RGBA", pixels[1], pixels[0])
        tmp_path = thumb_path.with_suffix(".tmp")
        image.save(tmp_path, format="PNG")
        tmp_path.replace(thumb_path)
    except OSError:
        pass  # A discardable disk cache must not prevent displaying a photo.
    return pixels


def _scan_library(library_dir: Path, thumb_dir: Path) -> List[Path]:
    # Re-read metadata on entry: parent imports can replace a file in place.
    paths, _dirty = _list_photos(library_dir, {})
    valid_names = {_thumb_name(path) for path in paths}
    if thumb_dir.exists():
        for path in thumb_dir.glob("*.png"):
            if path.name not in valid_names:
                try:
                    path.unlink()
                except OSError:
                    pass
    return paths


def _scale_to_fit(surface: pygame.Surface, size: Tuple[int, int]) -> pygame.Surface:
    target_w, target_h = size
    src_w, src_h = surface.get_size()
    scale = min(target_w / src_w, target_h / src_h)
    new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
    return pygame.transform.smoothscale(surface, new_size)


def _parse_exif_datetime(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        # EXIF uses "YYYY:MM:DD HH:MM:SS"
        return datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _photo_taken_at(path: Path) -> Optional[datetime]:
    if Image is None:
        return None
    try:
        with Image.open(path) as image:
            exif = image.getexif()
    except Exception:
        return None

    if not exif:
        return None
    for tag in _EXIF_DATE_TAGS:
        taken = _parse_exif_datetime(exif.get(tag))
        if taken is not None:
            return taken
    return None


def _list_photos(library_dir: Path, exif_cache: dict[str, Optional[float]]) -> Tuple[List[Path], bool]:
    dirty = False

    def sort_key(path: Path) -> Tuple[int, float, str]:
        nonlocal dirty
        rel = str(path.relative_to(library_dir))
        if rel in exif_cache:
            cached = exif_cache[rel]
            if cached is not None:
                return (0, -cached, path.name.lower())
        else:
            taken = _photo_taken_at(path)
            if taken is not None:
                exif_cache[rel] = taken.timestamp()
                dirty = True
                return (0, -exif_cache[rel], path.name.lower())
            exif_cache[rel] = None
            dirty = True
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (1, -mtime, path.name.lower())

    return (
        sorted((path for path in library_dir.iterdir() if _is_image(path)), key=sort_key),
        dirty,
    )


def _load_exif_cache(path: Path) -> dict[str, Optional[float]]:
    def _replace_cache_with_empty() -> dict[str, Optional[float]]:
        _save_exif_cache(path, {})
        return {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return _replace_cache_with_empty()
        normalized: dict[str, Optional[float]] = {}
        for key, val in data.items():
            if not isinstance(key, str):
                return _replace_cache_with_empty()
            if isinstance(val, (int, float)):
                normalized[key] = float(val)
            elif val is None:
                normalized[key] = None
            else:
                return _replace_cache_with_empty()
        return normalized
    except FileNotFoundError:
        return {}
    except Exception:
        # Unknown/corrupt cache: replace with canonical empty map.
        return _replace_cache_with_empty()


def _save_exif_cache(path: Path, data: dict[str, Optional[float]]) -> None:
    try:
        tmp_path = path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle)
        tmp_path.replace(path)
    except Exception:
        pass


class PhotosApp:
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
        self.photos_dir = dirs["photos"]
        self.library_dir = self.photos_dir / "library"
        self.thumb_dir = self.photos_dir / "thumbs" / "oriented-v1"
        self.exif_cache_path = self.thumb_dir / "exif_cache.json"

        if screen is None:
            self.screen, self.screen_rect = create_fullscreen_window()
        else:
            self.screen = screen
            self.screen_rect = screen_rect or screen.get_rect()
        self.clock = clock or pygame.time.Clock()

        base_strip_width = max(160, int(self.screen_rect.width * 0.25))
        self.strip_width = max(112, int(base_strip_width * 0.7))
        self.strip_rect = pygame.Rect(
            0,
            0,
            self.strip_width,
            self.screen_rect.height,
        )
        self.main_rect = pygame.Rect(self.strip_width, 0, self.screen_rect.width - self.strip_width, self.screen_rect.height)

        self.thumb_padding_x = 12
        self.thumb_gap = 12
        self.thumb_width = max(1, self.strip_rect.width - (self.thumb_padding_x * 2))
        self.thumb_size = self.thumb_width
        self.scroll_y = 0

        self.items: List[PhotoItem] = []
        self.current_index = 0
        self.current_image: Optional[pygame.Surface] = None
        photo_config = self.config.get("photos", {})
        self.thumb_idle_ms = int(photo_config.get("thumb_idle_ms", 400))
        self.thumb_scroll_idle_ms = int(photo_config.get("thumb_scroll_idle_ms", 700))
        self.thumb_cache_limit = max(8, min(256, int(photo_config.get("thumb_cache_limit", 48))))
        self._thumb_lru: OrderedDict[int, None] = OrderedDict()
        self._failed_thumbs: set[int] = set()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="photos")
        self._future: Optional[Future] = None
        self._job_kind = ""
        self._job_key = None
        self._generation = 0
        self._main_ready_key = None
        self._refresh_requested = False

        self.drag_start: Optional[Tuple[int, int]] = None
        self.drag_delta: Tuple[int, int] = (0, 0)
        self.strip_drag_last_y: Optional[int] = None
        self.strip_pressed_index: Optional[int] = None
        self.strip_drag_distance = 0
        self.pointer_down = False
        self.pointer_input = PointerInput()
        self.show_arrows = bool(self.config.get("photos", {}).get("show_arrows", False))
        self.font = theme.ui_font(18)

        self.home_button = Button(rect=theme.home_rect(self.screen_rect), fill=theme.PAPER)
        self.left_arrow = Button(rect=pygame.Rect(self.main_rect.left + 20, self.screen_rect.centery - 30, 50, 60), fill=theme.PAPER)
        self.right_arrow = Button(rect=pygame.Rect(self.main_rect.right - 70, self.screen_rect.centery - 30, 50, 60), fill=theme.PAPER)

        self.left_arrow.image = theme.icon("left", (40, 48))
        self.right_arrow.image = theme.icon("right", (40, 48))
        self.empty_icon = theme.icon("photos", (96, 96))
        self._refresh_library()

    def _handle_resume(self, reason: str) -> None:
        self.logger.info(f"Photos resume handling triggered: {reason}")
        self.pointer_input.reset()
        self.pointer_down = False
        self.drag_start = None
        self.drag_delta = (0, 0)
        self.strip_drag_last_y = None
        self.strip_pressed_index = None
        self.strip_drag_distance = 0
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

    def relaunch(self, screen: pygame.Surface, screen_rect: pygame.Rect, clock: pygame.time.Clock) -> None:
        self.screen = screen
        self.screen_rect = screen_rect
        self.clock = clock
        self.pointer_input.reset()
        self.scroll_y = 0
        self.current_index = 0
        self._refresh_library()
        self.drag_start = None
        self.drag_delta = (0, 0)
        self.strip_drag_last_y = None
        self.strip_pressed_index = None
        self.strip_drag_distance = 0
        self.pointer_down = False

    def _refresh_library(self) -> None:
        self._generation += 1
        self._refresh_requested = True
        self.current_image = None
        self.items = []
        self._thumb_lru.clear()
        self._failed_thumbs.clear()
        self._main_ready_key = None
        self._service_preparation(thumbnails=False)

    def _service_preparation(self, prefer_indices=None, *, thumbnails: bool = True) -> None:
        """Poll one bounded job, then submit at most one; never wait in a frame."""
        if self._future is not None:
            if not self._future.done():
                return
            kind, key = self._job_kind, self._job_key
            try:
                result = self._future.result()
            except Exception:
                result = None
                self.logger.exception("Photos background preparation failed")
            self._future = None
            if key[0] == self._generation:
                if kind == "scan":
                    self.items = [PhotoItem(path) for path in (result or [])]
                    self.current_index = 0
                elif kind == "main" and key == (self._generation, self.current_index):
                    self.current_image = _surface_from_pixels(result) if result else None
                    self._main_ready_key = key
                elif kind == "thumb":
                    idx = key[1]
                    if result:
                        self.items[idx].thumb = _surface_from_pixels(result)
                        self._thumb_lru[idx] = None
                        self._trim_thumbnail_cache()
                    else:
                        self._failed_thumbs.add(idx)
        if self._refresh_requested:
            self._refresh_requested = False
            self._submit_preparation("scan", (self._generation,), _scan_library, self.library_dir, self.thumb_dir)
        elif self.items:
            key = (self._generation, self.current_index)
            if self._main_ready_key != key:
                self._submit_preparation("main", key, _decode_photo, self.items[self.current_index].path, self.main_rect.size, True)
            elif thumbnails:
                indices = self._visible_indices() if prefer_indices is None else prefer_indices
                for idx in indices:
                    if idx in self._thumb_lru:
                        self._thumb_lru.move_to_end(idx)
                for idx in indices:
                    if self.items[idx].thumb is None and idx not in self._failed_thumbs:
                        item = self.items[idx]
                        self._submit_preparation("thumb", (self._generation, idx), _prepare_thumbnail,
                                                 item.path, self.thumb_dir / _thumb_name(item.path),
                                                 (self.thumb_width, self.thumb_size))
                        break

    def _submit_preparation(self, kind, key, function, *args) -> None:
        self._job_kind, self._job_key = kind, key
        self._future = self._executor.submit(function, *args)

    def _trim_thumbnail_cache(self) -> None:
        while len(self._thumb_lru) > self.thumb_cache_limit:
            idx, _ = self._thumb_lru.popitem(last=False)
            self.items[idx].thumb = None

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _thumb_slot(self) -> int:
        return self.thumb_size + self.thumb_gap

    def _thumb_y_for_index(self, idx: int) -> int:
        return self.thumb_gap - self.scroll_y + idx * self._thumb_slot()

    def _visible_index_bounds(self) -> Tuple[int, int]:
        if not self.items:
            return (0, -1)
        slot = self._thumb_slot()
        start = max(0, (self.scroll_y - self.thumb_gap) // slot - 1)
        end = min(len(self.items) - 1, (self.scroll_y + self.screen_rect.height - self.thumb_gap) // slot + 1)
        return (int(start), int(end))

    def _visible_indices(self) -> List[int]:
        start, end = self._visible_index_bounds()
        if end < start:
            return []
        return list(range(start, end + 1))

    def _load_next_thumbnail(self, prefer_indices: Optional[List[int]] = None) -> None:
        # Kept as the launcher's nonblocking prewarm entry point.
        self._service_preparation(prefer_indices)

    def _load_current_image(self) -> None:
        self.current_image = None
        self._main_ready_key = None
        self._service_preparation(thumbnails=False)

    def _change_index(self, delta: int) -> None:
        if not self.items:
            return
        self.current_index = (self.current_index + delta) % len(self.items)
        self._load_current_image()

    def _max_scroll(self) -> int:
        total_height = len(self.items) * (self.thumb_size + self.thumb_gap) + self.thumb_gap
        return max(0, total_height - self.screen_rect.height)

    def _thumb_index_at_pos(self, pos: Tuple[int, int]) -> Optional[int]:
        left = self.strip_rect.left + self.thumb_padding_x
        right = left + self.thumb_width
        if pos[0] < left or pos[0] > right:
            return None
        slot = self._thumb_slot()
        local_y = pos[1] - (self.thumb_gap - self.scroll_y)
        if local_y < 0:
            return None
        idx = int(local_y // slot)
        if idx < 0 or idx >= len(self.items):
            return None
        if (local_y % slot) > self.thumb_size:
            return None
        return idx

    def _scroll_thumbnails(self, delta: int) -> None:
        self.scroll_y = max(0, min(self._max_scroll(), self.scroll_y + delta))

    def _render(self) -> None:
        self.screen.fill(theme.BACKGROUND)
        pygame.draw.rect(self.screen, theme.PANEL, self.strip_rect, border_radius=18)

        if self.current_image:
            image_rect = self.current_image.get_rect(center=self.main_rect.center)
            self.screen.blit(self.current_image, image_rect)
        elif not self.items and self._future is None:
            center = self.main_rect.center
            self.screen.blit(self.empty_icon, self.empty_icon.get_rect(center=(center[0], center[1] - 24)))
            text = self.font.render("No photos yet", True, theme.MUTED)
            self.screen.blit(text, text.get_rect(center=(center[0], center[1] + 48)))

        start, end = self._visible_index_bounds()
        for idx in range(start, end + 1):
            item = self.items[idx]
            y = self._thumb_y_for_index(idx)
            rect = pygame.Rect(
                self.strip_rect.left + self.thumb_padding_x,
                y,
                self.thumb_width,
                self.thumb_size,
            )
            theme.card(self.screen, rect, selected=idx == self.current_index)
            if item.thumb:
                thumb_rect = item.thumb.get_rect(center=rect.center)
                self.screen.blit(item.thumb, thumb_rect)
            pygame.draw.rect(self.screen, theme.BORDER, rect, width=1)
            if idx == self.current_index:
                theme.selection(self.screen, rect, radius=4)

        draw_home_button(self.screen, self.home_button.rect)

        if self.show_arrows:
            self.left_arrow.draw(self.screen, self.font)
            self.right_arrow.draw(self.screen, self.font)

        pygame.display.flip()

    def run(self, *, quit_on_exit: bool = True) -> None:
        try:
            running = True
            self._render()
            last_input_ms = pygame.time.get_ticks()
            last_scroll_ms = last_input_ms
            last_frame_time = time.monotonic()
            while running and not health.stopping():
                now = time.monotonic()
                if now - last_frame_time > 2.0:
                    self._handle_resume("frame-time gap")
                last_frame_time = now
                discard_input = False
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                        break
                    if discard_input:
                        continue
                    if event.type in _INPUT_RESET_EVENTS:
                        self._handle_resume("window/input state event")
                        # clear() cannot remove events already in this batch.
                        discard_input = True
                        continue
                    if self._should_reset_for_key(event):
                        self._handle_resume("ignored keyboard shortcut")
                        discard_input = True
                        continue
                    if not self.pointer_input.accept(event):
                        continue
                    if event.type in {
                        pygame.MOUSEMOTION,
                        pygame.MOUSEBUTTONDOWN,
                        pygame.MOUSEBUTTONUP,
                        pygame.MOUSEWHEEL,
                        pygame.KEYDOWN,
                        getattr(pygame, "FINGERDOWN", None),
                        getattr(pygame, "FINGERUP", None),
                        FINGERMOTION,
                    }:
                        last_input_ms = pygame.time.get_ticks()
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        running = False
                        break
                    elif is_primary_pointer_event(event, is_down=True):
                        if self.pointer_down:
                            continue
                        pos = pointer_event_pos(event, self.screen_rect)
                        if pos is None:
                            continue
                        self.pointer_down = True
                        if self.home_button.hit(pos):
                            running = False
                            break
                        elif self.strip_rect.collidepoint(pos):
                            self.strip_drag_last_y = pos[1]
                            self.strip_pressed_index = self._thumb_index_at_pos(pos)
                            self.strip_drag_distance = 0
                        elif self.main_rect.collidepoint(pos):
                            self.drag_start = pos
                            self.drag_delta = (0, 0)
                        if self.show_arrows:
                            if self.left_arrow.hit(pos):
                                self._change_index(-1)
                            elif self.right_arrow.hit(pos):
                                self._change_index(1)
                    elif event.type in {pygame.MOUSEMOTION, FINGERMOTION}:
                        if not self.pointer_down:
                            continue
                        pos = pointer_event_pos(event, self.screen_rect)
                        if pos is None:
                            continue
                        if self.drag_start:
                            self.drag_delta = (pos[0] - self.drag_start[0], pos[1] - self.drag_start[1])
                        if self.strip_drag_last_y is not None:
                            dy = pos[1] - self.strip_drag_last_y
                            self._scroll_thumbnails(-dy)
                            last_scroll_ms = pygame.time.get_ticks()
                            self.strip_drag_distance += abs(dy)
                            self.strip_drag_last_y = pos[1]
                    elif is_primary_pointer_event(event, is_down=False):
                        if not self.pointer_down:
                            continue
                        self.pointer_down = False
                        pos = pointer_event_pos(event, self.screen_rect)
                        if pos is None:
                            continue
                        if self.drag_start:
                            dx, dy = self.drag_delta
                            if abs(dx) > SWIPE_THRESHOLD and abs(dx) > abs(dy):
                                if dx < 0:
                                    self._change_index(1)
                                else:
                                    self._change_index(-1)
                            self.drag_start = None
                            self.drag_delta = (0, 0)
                        if (
                            self.strip_pressed_index is not None
                            and self.strip_drag_distance < DRAG_THRESHOLD
                            and self._thumb_index_at_pos(pos) == self.strip_pressed_index
                        ):
                            self.current_index = self.strip_pressed_index
                            self._load_current_image()
                        self.strip_drag_last_y = None
                        self.strip_pressed_index = None
                        self.strip_drag_distance = 0
                    elif event.type == pygame.MOUSEWHEEL:
                        if self.strip_rect.collidepoint(pygame.mouse.get_pos()):
                            self._scroll_thumbnails(-event.y * SCROLL_STEP)
                            last_scroll_ms = pygame.time.get_ticks()
                    elif event.type == pygame.MOUSEBUTTONDOWN and event.button in {4, 5}:
                        if self.strip_rect.collidepoint(event.pos):
                            self._scroll_thumbnails(-SCROLL_STEP if event.button == 4 else SCROLL_STEP)
                            last_scroll_ms = pygame.time.get_ticks()

                self._render()
                now_ms = pygame.time.get_ticks()
                scroll_active = now_ms - last_scroll_ms < self.thumb_scroll_idle_ms
                active_input = now_ms - last_input_ms < self.thumb_idle_ms
                self._service_preparation(thumbnails=not scroll_active and not active_input)
                self.clock.tick(60)
                health.frame_complete()

        finally:
            self.pointer_input.reset()
            if quit_on_exit:
                self.close()
                pygame.quit()


def main() -> None:
    app = None
    try:
        app = PhotosApp()
        app.run(quit_on_exit=True)
    except Exception:
        logger = get_runtime_logger(get_data_root(load_config()))
        logger.exception("Photos app crashed in main()")
    finally:
        if app is not None:
            app.close()
        pygame.quit()


def run_embedded(
    screen: pygame.Surface,
    screen_rect: pygame.Rect,
    clock: pygame.time.Clock,
    *,
    app: Optional[PhotosApp] = None,
) -> PhotosApp:
    if app is None:
        app = PhotosApp(screen=screen, screen_rect=screen_rect, clock=clock)
    else:
        app.relaunch(screen, screen_rect, clock)
    try:
        app.run(quit_on_exit=False)
    except BaseException:
        app.close()
        raise
    return app


if __name__ == "__main__":
    main()
