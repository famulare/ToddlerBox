from __future__ import annotations

import shlex
import os
import shutil
import subprocess
import sys
import time
import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import pygame

from toddlerbox.config import load_config
from toddlerbox.music.app import run_embedded as run_music_embedded
from toddlerbox.math.app import run_embedded as run_math_embedded
from toddlerbox.reading.app import run_embedded as run_reading_embedded
from toddlerbox.ui import theme
from toddlerbox.paths import get_data_root
from toddlerbox.paint.app import run_embedded as run_paint_embedded
from toddlerbox.photos.app import PhotosApp, run_embedded as run_photos_embedded
from toddlerbox.runtime import RuntimeLogger, get_runtime_logger
from toddlerbox.runtime import health, control
from toddlerbox.typing.app import run_embedded as run_typing_embedded
from toddlerbox.ui.common import (
    Button,
    PointerInput,
    create_fullscreen_window,
    draw_placeholder_icon,
    ignore_system_shortcut,
    is_primary_pointer_event,
    is_escape_chord,
    load_image,
    pointer_event_pos,
    set_env_for_child,
)

WINDOW_FOCUS_GAINED = getattr(pygame, "WINDOWFOCUSGAINED", None)
APP_DID_ENTER_FOREGROUND = getattr(pygame, "APP_DIDENTERFOREGROUND", None)


@dataclass
class LauncherApp:
    name: str
    icon_path: str
    command: List[str]


_EMBEDDED_RUNNERS: Dict[str, Callable[[pygame.Surface, pygame.Rect, pygame.time.Clock], None]] = {
    "toddlerbox.paint": run_paint_embedded,
    "toddlerbox.typing": run_typing_embedded,
    "toddlerbox.music": run_music_embedded,
    "toddlerbox.reading": run_reading_embedded,
    "toddlerbox.math": run_math_embedded,
}


def _parse_command(cmd: Any) -> List[str]:
    if isinstance(cmd, list):
        return [str(part) for part in cmd]
    if isinstance(cmd, str):
        return shlex.split(cmd)
    return []


def _load_apps(config: Dict[str, Any]) -> List[LauncherApp]:
    apps = []
    for app in config.get("launcher", {}).get("apps", []):
        apps.append(
            LauncherApp(
                name=str(app.get("name", "App")),
                icon_path=str(app.get("icon_path", "")),
                command=_parse_command(app.get("command", "")),
            )
        )
    return apps


def _resolve_command(command: List[str]) -> List[str]:
    if not command:
        return []
    executable = command[0]
    if executable not in {"python", "python3"}:
        return command
    interpreter = sys.executable or shutil.which("python3") or shutil.which("python")
    if interpreter:
        return [interpreter, *command[1:]]
    return command


def _module_name_for_command(command: List[str]) -> Optional[str]:
    if "-m" not in command:
        return None
    idx = command.index("-m")
    if idx + 1 >= len(command):
        return None
    return command[idx + 1]


def _build_buttons(apps: List[LauncherApp], screen_rect: pygame.Rect) -> List[Button]:
    if not apps:
        return []
    icon_size = max(120, min(184, int(min(screen_rect.width, screen_rect.height) * 0.23)))
    gap = int(icon_size * 0.3)
    fit_columns = max(1, (screen_rect.w - 32 + gap) // (icon_size + gap))
    standard_modules = [f"toddlerbox.{name}" for name in ("paint", "photos", "music", "typing", "reading", "math")]
    if [_module_name_for_command(app.command) for app in apps] == standard_modules:
        rows, columns = 2, 3
    else:
        rows = math.ceil(len(apps) / fit_columns)
        columns = math.ceil(len(apps) / rows)
    total_height = rows * icon_size + (rows - 1) * gap
    start_y = screen_rect.centery - total_height // 2
    buttons = []
    for idx, app in enumerate(apps):
        row, column = divmod(idx, columns)
        row_count = min(columns, len(apps) - row * columns)
        row_width = row_count * icon_size + (row_count - 1) * gap
        start_x = screen_rect.centerx - row_width // 2
        rect = pygame.Rect(start_x + column * (icon_size + gap), start_y + row * (icon_size + gap), icon_size, icon_size)
        module = _module_name_for_command(app.command)
        image = load_image(app.icon_path)
        if image is None and module in {"toddlerbox.music", "toddlerbox.reading", "toddlerbox.math"}:
            image = theme.artwork(module.rsplit(".", 1)[1], (icon_size, icon_size))
        if image is not None:
            image = theme.activity_tile(image, app.name, icon_size)
        buttons.append(
            Button(
                rect=rect,
                label=app.name,
                image=image,
                fill=theme.PAPER,
                border_width=0,
            )
        )
    return buttons


def _launch_app(
    app: LauncherApp,
    screen: pygame.Surface,
    screen_rect: pygame.Rect,
    clock: pygame.time.Clock,
    logger: RuntimeLogger,
    *,
    photos_app: Optional[PhotosApp] = None,
) -> tuple[bool, Optional[PhotosApp]]:
    module_name = _module_name_for_command(app.command)
    if module_name == "toddlerbox.photos":
        try:
            photos_app = run_photos_embedded(screen, screen_rect, clock, app=photos_app)
        except Exception:
            logger.exception("Photos app crashed in embedded mode")
            if photos_app is not None:
                photos_app.close()
            photos_app = None
        return False, photos_app

    runner = _EMBEDDED_RUNNERS.get(module_name) if module_name else None
    if runner is not None:
        try:
            runner(screen, screen_rect, clock)
        except Exception:
            logger.exception(f"Embedded app crashed: {module_name}")
            return False, photos_app
        return False, photos_app

    if os.environ.get("TODDLERBOX_HEALTH_SOCKET"):
        logger.info(f"Unsupported external activity refused in supervised child session: {app.name}")
        return False, photos_app
    command = _resolve_command(app.command)
    if not command:
        return False, photos_app
    try:
        child = subprocess.Popen(
            command,
            env=set_env_for_child(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        child.wait()
    except Exception:
        logger.exception(f"Subprocess app launch failed: {' '.join(command)}")
        return False, photos_app
    return True, photos_app


def _pointer_event_types() -> list[int]:
    pointer_events = [pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP]
    finger_down = getattr(pygame, "FINGERDOWN", None)
    finger_up = getattr(pygame, "FINGERUP", None)
    if finger_down is not None:
        pointer_events.append(finger_down)
    if finger_up is not None:
        pointer_events.append(finger_up)
    return pointer_events


def _is_resume_event(event: pygame.event.Event) -> bool:
    return event.type in {WINDOW_FOCUS_GAINED, APP_DID_ENTER_FOREGROUND}


def _restore_launcher_window() -> tuple[pygame.Surface, pygame.Rect]:
    existing = pygame.display.get_surface()
    if existing is not None:
        return existing, existing.get_rect()
    return create_fullscreen_window()


def _draw_launcher_frame(
    screen: pygame.Surface,
    background: tuple[int, int, int],
    apps: List[LauncherApp],
    buttons: List[Button],
) -> None:
    screen.fill(background)
    for app, button in zip(apps, buttons):
        if button.image is None:
            draw_placeholder_icon(screen, button.rect, app.name, border_width=0)
        else:
            button.draw(screen)
    control.before_flip(screen)
    pygame.display.flip()


def main() -> None:
    config = load_config()
    logger = get_runtime_logger(get_data_root(config))
    apps = _load_apps(config)
    screen, screen_rect = create_fullscreen_window()
    clock = pygame.time.Clock()
    background = theme.BACKGROUND

    photos_app: Optional[PhotosApp] = None
    try:
        buttons = _build_buttons(apps, screen_rect)
        prewarm_enabled = bool(config.get("launcher", {}).get("photos_prewarm", True))
        prewarm_idle_ms = int(config.get("launcher", {}).get("photos_prewarm_idle_ms", 600))
        prewarm_batch = int(config.get("launcher", {}).get("photos_prewarm_batch", 2))
        if prewarm_enabled:
            try:
                photos_app = PhotosApp(screen=screen, screen_rect=screen_rect, clock=clock)
            except Exception:
                logger.exception("Photos prewarm initialization failed")
                photos_app = None
        pointer_block_until = 0.0
        pointer = PointerInput()
        last_input = time.monotonic()
        last_frame_time = time.monotonic()

        running = True
        _draw_launcher_frame(screen, background, apps, buttons)
        while running and not health.stopping():
            now = time.monotonic()
            if now - last_frame_time > 2.0:
                logger.info("Launcher resume detected via frame-time gap")
                pygame.event.clear(_pointer_event_types())
                pointer.reset()
                pointer_block_until = now + 0.25
            last_frame_time = now
            for event in pygame.event.get():
                if _is_resume_event(event):
                    logger.info("Launcher resumed from focus/background event")
                    pygame.event.clear(_pointer_event_types())
                    pointer.reset()
                    pointer_block_until = time.monotonic() + 0.25
                    continue
                if not pointer.accept(event):
                    continue
                if event.type in {
                    pygame.MOUSEMOTION,
                    pygame.MOUSEBUTTONDOWN,
                    pygame.MOUSEBUTTONUP,
                    pygame.MOUSEWHEEL,
                    pygame.KEYDOWN,
                }:
                    last_input = time.monotonic()
                if event.type == pygame.QUIT:
                    running = False
                elif is_escape_chord(event) and not os.environ.get("TODDLERBOX_HEALTH_SOCKET"):
                    running = False
                    break
                elif ignore_system_shortcut(event):
                    continue
                elif is_primary_pointer_event(event, is_down=True):
                    last_input = time.monotonic()
                    if time.monotonic() < pointer_block_until:
                        continue
                    pos = pointer_event_pos(event, screen_rect)
                    if pos is None:
                        continue
                    for app, button in zip(apps, buttons):
                        if button.hit(pos):
                            logger.info(f"Launching app: {app.name}")
                            used_subprocess, photos_app = _launch_app(
                                app, screen, screen_rect, clock, logger, photos_app=photos_app,
                            )
                            if used_subprocess:
                                screen, screen_rect = _restore_launcher_window()
                                buttons = _build_buttons(apps, screen_rect)
                            pygame.event.clear(_pointer_event_types())
                            pointer.reset()
                            pointer_block_until = time.monotonic() + 0.25
                            last_input = time.monotonic()
                            logger.info(f"Returned to launcher from app: {app.name}")
                            _draw_launcher_frame(screen, background, apps, buttons)
                            break
                    else:
                        continue
                    # Scene entry invalidates the remainder of this fetched input batch.
                    break

            _draw_launcher_frame(screen, background, apps, buttons)
            now = time.monotonic()
            if photos_app and now - last_input >= (prewarm_idle_ms / 1000.0) and now >= pointer_block_until:
                for _ in range(prewarm_batch):
                    try:
                        photos_app._load_next_thumbnail()
                    except Exception:
                        logger.exception("Photos prewarm thumbnail load failed")
                        break
            clock.tick(60)
            health.frame_complete()

    finally:
        if photos_app is not None:
            photos_app.close()
        pygame.quit()
        health.shutdown_complete()


if __name__ == "__main__":
    main()
