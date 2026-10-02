from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import time
from typing import List, Optional, Tuple

import pygame
from toddlerbox.runtime import health
try:
    from PIL import Image
except Exception:
    Image = None

FINGERMOTION = getattr(pygame, "FINGERMOTION", None)

# --- Tuning constants ---
DRAG_THRESHOLD = 10
SWIPE_THRESHOLD = 80
SCROLL_STEP = 40

from toddlerbox.config import load_config
from toddlerbox.paths import ensure_directories, get_data_root
from toddlerbox.runtime import RuntimeLogger, get_runtime_logger
from toddlerbox.ui.common import (
    Button,
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


def _load_photo_surface(path: Path, *, for_thumbnail: bool = False) -> pygame.Surface:
    image = pygame.image.load(str(path))
    suffix = path.suffix.lower()
    if for_thumbnail and suffix in {".jpg", ".jpeg", ".bmp"}:
        return image.convert()
    if suffix in {".jpg", ".jpeg", ".bmp"}:
        return image.convert()
    return image.convert_alpha()


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
        self.thumb_dir = self.photos_dir / "thumbs"
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

        self.exif_cache = _load_exif_cache(self.exif_cache_path)
        photo_paths, cache_dirty = _list_photos(self.library_dir, self.exif_cache)
        self.items = [PhotoItem(path) for path in photo_paths]
        self.current_index = 0
        self.current_image: Optional[pygame.Surface] = None
        self.initial_thumb_count = int(self.config.get("photos", {}).get("initial_thumbs", 10))
        self.thumb_load_batch = int(self.config.get("photos", {}).get("thumb_batch", 2))
        self.thumb_idle_ms = int(self.config.get("photos", {}).get("thumb_idle_ms", 400))
        self.thumb_scroll_idle_ms = int(self.config.get("photos", {}).get("thumb_scroll_idle_ms", 700))
        self.thumb_time_budget_ms = int(self.config.get("photos", {}).get("thumb_time_budget_ms", 3))
        self._init_thumb_queue()
        self._load_initial_thumbnails()
        if cache_dirty:
            _save_exif_cache(self.exif_cache_path, self.exif_cache)
        self._cleanup_caches()
        self._load_current_image()

        self.drag_start: Optional[Tuple[int, int]] = None
        self.drag_delta: Tuple[int, int] = (0, 0)
        self.strip_drag_last_y: Optional[int] = None
        self.strip_pressed_index: Optional[int] = None
        self.strip_drag_distance = 0
        self.pointer_down = False
        self.show_arrows = bool(self.config.get("photos", {}).get("show_arrows", False))
        self.font = pygame.font.SysFont("sans", 18)

        self.home_button = Button(rect=pygame.Rect(self.screen_rect.width - 90, 20, 70, 50), fill=(240, 240, 240))
        self.left_arrow = Button(rect=pygame.Rect(self.main_rect.left + 20, self.screen_rect.centery - 30, 50, 60), fill=(245, 245, 245))
        self.right_arrow = Button(rect=pygame.Rect(self.main_rect.right - 70, self.screen_rect.centery - 30, 50, 60), fill=(245, 245, 245))

    def _handle_resume(self, reason: str) -> None:
        self.logger.info(f"Photos resume handling triggered: {reason}")
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
        self.scroll_y = 0
        self.current_index = 0
        self._load_current_image()
        self.drag_start = None
        self.drag_delta = (0, 0)
        self.strip_drag_last_y = None
        self.strip_pressed_index = None
        self.strip_drag_distance = 0
        self.pointer_down = False

    def _init_thumb_queue(self) -> None:
        self._pending_order = list(range(len(self.items)))
        self._pending_set = set(self._pending_order)
        self._pending_cursor = 0

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

    def _load_initial_thumbnails(self) -> None:
        initial_count = max(0, min(self.initial_thumb_count, len(self._pending_order)))
        for idx in range(initial_count):
            self._load_thumbnail_for_index(idx)
            self._pending_set.discard(idx)
        self._pending_cursor = initial_count

    def _visible_indices(self) -> List[int]:
        start, end = self._visible_index_bounds()
        if end < start:
            return []
        return list(range(start, end + 1))

    def _next_pending_index(self, prefer_indices: Optional[List[int]]) -> Optional[int]:
        if prefer_indices:
            for idx in prefer_indices:
                if idx in self._pending_set:
                    return idx
        while self._pending_cursor < len(self._pending_order):
            idx = self._pending_order[self._pending_cursor]
            self._pending_cursor += 1
            if idx in self._pending_set:
                return idx
        return None

    def _load_next_thumbnail(self, prefer_indices: Optional[List[int]] = None) -> None:
        if not self._pending_set:
            return
        idx = self._next_pending_index(prefer_indices)
        if idx is None:
            return
        self._load_thumbnail_for_index(idx)
        self._pending_set.discard(idx)

    def _load_thumbnail_for_index(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.items):
            return
        item = self.items[idx]
        if item.thumb is not None:
            return
        thumb_path = self.thumb_dir / _thumb_name(item.path)
        try:
            source_mtime = item.path.stat().st_mtime
        except OSError:
            return
        if thumb_path.exists():
            try:
                if thumb_path.stat().st_mtime >= source_mtime:
                    loaded_thumb = _load_photo_surface(thumb_path, for_thumbnail=True)
                    item.thumb = self._fit_thumb_surface(loaded_thumb)
                    return
            except Exception:
                pass
        try:
            image = _load_photo_surface(item.path, for_thumbnail=True)
            thumb = self._fit_thumb_surface(image)
            pygame.image.save(thumb, str(thumb_path))
            item.thumb = thumb
        except Exception:
            item.thumb = None

    def _cleanup_caches(self) -> None:
        try:
            library_set = {str(path.relative_to(self.library_dir)) for path in self.library_dir.iterdir() if _is_image(path)}
        except Exception:
            library_set = set()

        cache_dirty = False
        for rel in list(self.exif_cache.keys()):
            if rel not in library_set:
                self.exif_cache.pop(rel, None)
                cache_dirty = True
        if cache_dirty:
            _save_exif_cache(self.exif_cache_path, self.exif_cache)

        try:
            for thumb_path in self.thumb_dir.iterdir():
                if thumb_path.name == self.exif_cache_path.name or thumb_path.suffix.lower() != ".png":
                    continue
                name = thumb_path.stem
                if "_" not in name:
                    continue
                stem, suffix = name.rsplit("_", 1)
                source_path = self.library_dir / f"{stem}.{suffix}"
                if not source_path.exists():
                    try:
                        thumb_path.unlink()
                    except Exception:
                        pass
        except Exception:
            pass

    def _fit_thumb_surface(self, surface: pygame.Surface) -> pygame.Surface:
        if surface.get_width() <= self.thumb_width and surface.get_height() <= self.thumb_size:
            return surface
        return _scale_to_fit(surface, (self.thumb_width, self.thumb_size))

    def _load_current_image(self) -> None:
        if not self.items:
            self.current_image = None
            return
        path = self.items[self.current_index].path
        try:
            image = _load_photo_surface(path, for_thumbnail=False)
            self.current_image = _scale_to_fit(image, self.main_rect.size)
        except Exception:
            self.current_image = None

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
        self.screen.fill((246, 246, 246))
        pygame.draw.rect(self.screen, (230, 230, 230), self.strip_rect)

        if self.current_image:
            image_rect = self.current_image.get_rect(center=self.main_rect.center)
            self.screen.blit(self.current_image, image_rect)
        else:
            text = self.font.render("No photos found", True, (50, 50, 50))
            self.screen.blit(text, text.get_rect(center=self.main_rect.center))

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
            if item.thumb:
                thumb_rect = item.thumb.get_rect(center=rect.center)
                self.screen.blit(item.thumb, thumb_rect)
            pygame.draw.rect(self.screen, (120, 120, 120), rect, width=2)
            if idx == self.current_index:
                pygame.draw.rect(self.screen, (200, 60, 60), rect, width=3)

        draw_home_button(self.screen, self.home_button.rect)

        if self.show_arrows:
            self.left_arrow.draw(self.screen, self.font)
            self.right_arrow.draw(self.screen, self.font)

        pygame.display.flip()

    def run(self, *, quit_on_exit: bool = True) -> None:
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
            for event in pygame.event.get():
                if event.type in _INPUT_RESET_EVENTS:
                    self._handle_resume("window/input state event")
                    continue
                if self._should_reset_for_key(event):
                    self._handle_resume("ignored keyboard shortcut")
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
                if event.type == pygame.QUIT:
                    running = False
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                elif is_primary_pointer_event(event, is_down=True):
                    if self.pointer_down:
                        continue
                    pos = pointer_event_pos(event, self.screen_rect)
                    if pos is None:
                        continue
                    self.pointer_down = True
                    if self.home_button.hit(pos):
                        running = False
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
                elif event.type == pygame.MOUSEMOTION:
                    if not self.pointer_down:
                        continue
                    if self.drag_start:
                        self.drag_delta = (event.pos[0] - self.drag_start[0], event.pos[1] - self.drag_start[1])
                    if self.strip_drag_last_y is not None:
                        dy = event.pos[1] - self.strip_drag_last_y
                        self._scroll_thumbnails(-dy)
                        last_scroll_ms = pygame.time.get_ticks()
                        self.strip_drag_distance += abs(dy)
                        self.strip_drag_last_y = event.pos[1]
                elif FINGERMOTION is not None and event.type == FINGERMOTION and self.pointer_down:
                    pos = (int(event.x * self.screen_rect.width), int(event.y * self.screen_rect.height))
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
            budget_end = now_ms + self.thumb_time_budget_ms
            visible_indices = self._visible_indices()
            if not scroll_active:
                batch = 1 if active_input else self.thumb_load_batch
                for _ in range(batch):
                    self._load_next_thumbnail(visible_indices)
                    if pygame.time.get_ticks() >= budget_end:
                        break
            self.clock.tick(60)
            health.frame_complete()

        if quit_on_exit:
            pygame.quit()


def main() -> None:
    try:
        PhotosApp().run(quit_on_exit=True)
    except Exception:
        logger = get_runtime_logger(get_data_root(load_config()))
        logger.exception("Photos app crashed in main()")
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
    app.run(quit_on_exit=False)
    return app


if __name__ == "__main__":
    main()
