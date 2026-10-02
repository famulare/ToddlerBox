from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from heapq import nlargest
from pathlib import Path
import time
from typing import Dict, List, Optional, Tuple

import pygame

FINGERMOTION = getattr(pygame, "FINGERMOTION", None)

# --- Tuning constants ---
DRAG_THRESHOLD = 10
SCROLL_STEP = 40
UNDO_MAX_DEPTH = 20
RECALL_READ_BYTES = 16 * 1024 * 1024

from toddlerbox.config import load_config
from toddlerbox.paths import ensure_directories, get_data_root
from toddlerbox.runtime import RuntimeLogger, get_runtime_logger
from toddlerbox.runtime import health
from toddlerbox.runtime.persistence import has_archive_reserve, write_bytes, sync_directory
from toddlerbox.ui.common import (
    Button,
    PointerInput,
    create_fullscreen_window,
    draw_home_button,
    is_primary_pointer_event,
    pointer_event_pos,
)

WINDOW_FOCUS_GAINED = getattr(pygame, "WINDOWFOCUSGAINED", None)
APP_DID_ENTER_FOREGROUND = getattr(pygame, "APP_DIDENTERFOREGROUND", None)


@dataclass
class Glyph:
    char: str
    size: int
    style: str


@dataclass
class EditOp:
    kind: str
    row: int
    col: int
    glyph: Optional[Glyph] = None
    newline: bool = False
    cursor_row: int = 0
    cursor_col: int = 0


@dataclass
class RecallSession:
    label: str
    preview: str
    rich_lines: List[List[Glyph]]
    is_current: bool = False


@dataclass
class VisualLine:
    row: int
    start_col: int
    end_col: int
    glyphs: List[Glyph]
    widths: List[int]
    height: int


@dataclass
class _Token:
    start: int
    end: int
    widths: List[int]
    is_space: bool


def _wrap_tokens(tokens: List[_Token], max_width: int) -> List[Tuple[int, int]]:
    if max_width <= 0:
        return []
    lines: List[Tuple[int, int]] = []
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    line_width = 0
    for token in tokens:
        token_width = sum(token.widths)
        if token_width <= max_width:
            if line_width == 0:
                line_start = token.start
                line_end = token.end
                line_width = token_width
            elif line_width + token_width <= max_width:
                line_end = token.end
                line_width += token_width
            else:
                if line_start is not None and line_end is not None:
                    lines.append((line_start, line_end))
                line_start = token.start
                line_end = token.end
                line_width = token_width
            continue

        if line_width > 0:
            if line_start is not None and line_end is not None:
                lines.append((line_start, line_end))
            line_start = None
            line_end = None
            line_width = 0

        idx = token.start
        i = 0
        widths = token.widths
        while i < len(widths):
            acc = 0
            j = i
            while j < len(widths) and (acc + widths[j] <= max_width or acc == 0):
                acc += widths[j]
                j += 1
            lines.append((idx + i, idx + j))
            i = j

    if line_width > 0 and line_start is not None and line_end is not None:
        lines.append((line_start, line_end))
    return lines


def _preview_text(text: str, limit: int = 150) -> str:
    normalized = " ".join(text.split())
    return normalized[:limit]


def _create_text_font(size: int, style: str = "plain") -> pygame.font.Font:
    bold = style == "bold"
    italic = style == "italic"
    if pygame.font.match_font("ubuntu"):
        return pygame.font.SysFont("ubuntu", size, bold=bold, italic=italic)
    return pygame.font.SysFont("sans", size, bold=bold, italic=italic)


def _serialize_rich_lines(lines: List[List[Glyph]]) -> List[List[dict]]:
    return [
        [{"char": glyph.char, "size": glyph.size, "style": glyph.style} for glyph in line]
        for line in lines
    ]


def _deserialize_rich_lines(payload: object) -> Optional[List[List[Glyph]]]:
    if not isinstance(payload, list):
        return None
    parsed: List[List[Glyph]] = []
    for raw_line in payload:
        if not isinstance(raw_line, list):
            return None
        parsed_line: List[Glyph] = []
        for raw_glyph in raw_line:
            if not isinstance(raw_glyph, dict):
                return None
            char = raw_glyph.get("char")
            size = raw_glyph.get("size")
            style = raw_glyph.get("style")
            if not isinstance(char, str) or len(char) != 1:
                return None
            if not isinstance(size, int) or size <= 0:
                return None
            if style not in {"plain", "bold", "italic"}:
                return None
            parsed_line.append(Glyph(char=char, size=size, style=style))
        parsed.append(parsed_line)
    return parsed if parsed else [[]]


def _clone_rich_lines(lines: List[List[Glyph]]) -> List[List[Glyph]]:
    return [[Glyph(char=g.char, size=g.size, style=g.style) for g in line] for line in lines]


def _rich_to_text(lines: List[List[Glyph]]) -> str:
    return "\n".join("".join(g.char for g in line) for line in lines)


def _recall_session(raw: bytes) -> Optional[RecallSession]:
    try:
        record = json.loads(raw)
        if not isinstance(record, dict) or record.get("version", 1) != 1:
            return None
        rich_lines = _deserialize_rich_lines(record.get("rich_lines"))
        if rich_lines is None:
            return None
        return RecallSession(
            label=str(record.get("timestamp") or "Saved"),
            preview=_preview_text(_rich_to_text(rich_lines)),
            rich_lines=rich_lines,
        )
    except (ValueError, UnicodeError):
        return None


def _load_recent_sessions(path: Path, *, limit: int = 200) -> List[RecallSession]:
    """Read a bounded recent window, preserving all older work on disk.

    Atomic archives supersede the legacy append-only log. Limit both candidate
    files and bytes read so damaged or unusually large history cannot cause an
    unbounded recall scan. Oversized records remain available for parent recovery.
    """
    if limit <= 0:
        return []
    recent: List[RecallSession] = []
    budget = RECALL_READ_BYTES
    for archive in nlargest(limit, (path.parent / "archive").glob("*.json")):
        if budget <= 0:
            break
        try:
            with archive.open("rb") as handle:
                size = archive.stat().st_size
                if size > budget:
                    continue
                raw = handle.read(budget)
            budget -= len(raw)
            item = _recall_session(raw)
            if item is not None:
                recent.append(item)
        except OSError:
            continue
    if len(recent) >= limit or budget <= 0:
        return recent

    # Seek from the end: old JSONL files can grow indefinitely. A partial first
    # record in the bounded tail is discarded; complete later records survive.
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            start = max(0, handle.tell() - budget)
            handle.seek(start)
            tail = handle.read(budget)
        records = tail.splitlines()
        if start and records:
            records = records[1:]
        for raw in reversed(records):
            item = _recall_session(raw)
            if item is not None:
                recent.append(item)
                if len(recent) == limit:
                    break
    except OSError:
        pass
    return recent


class TypingApp:
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
        self.typing_dir = dirs["typing"]
        self.sessions_path = self.typing_dir / "sessions.jsonl"
        self.current_path = self.typing_dir / "current.json"
        self.last_autosave = time.monotonic()
        self.autosave_interval = max(1, int(self.config.get("typing", {}).get("autosave_seconds", 5)))
        self._saved_payload: bytes | None = None
        self._save_blocked = False
        self._layout_key = None
        self._layout_revision = 0
        self._visual_lines: List[VisualLine] = []

        if screen is None:
            self.screen, self.screen_rect = create_fullscreen_window()
        else:
            self.screen = screen
            self.screen_rect = screen_rect or screen.get_rect()
        self.clock = clock or pygame.time.Clock()

        self.ui_font = pygame.font.SysFont("sans", 20)
        self.default_text_size = 25
        self.size_values = [self.default_text_size, self.default_text_size * 2, self.default_text_size * 4]
        self.text_style = "plain"
        self.current_text_size = self.default_text_size
        self.font_cache: Dict[Tuple[int, str], pygame.font.Font] = {}
        self.size_sample_fonts = {size: _create_text_font(size, "plain") for size in self.size_values}
        self.default_line_style = (self.default_text_size, "plain")

        self.rich_lines: List[List[Glyph]] = [[]]
        self.line_styles: List[Tuple[int, str]] = [self.default_line_style]
        self.text_lines: List[str] = [""]
        self.undo_stack: List[EditOp] = []
        self.cursor_row = 0
        self.cursor_col = 0
        self.cursor_x_target: Optional[int] = None
        self._cursor_x_target_dirty = True
        self.text_scroll_y = 0

        self.margin = 16
        self.menu_pad = 10
        self.menu_gap = 10
        self.menu_bg = (238, 234, 226)
        self.tool_size = max(44, min(56, int(self.screen_rect.height * 0.06)))
        base_panel_width = self.tool_size * 2 + self.menu_gap + self.menu_pad * 2
        panel_width = min(self.screen_rect.width - (self.margin * 3 + 240), base_panel_width * 2)
        self.controls_rect = pygame.Rect(
            self.margin,
            self.margin,
            max(220, panel_width),
            self.screen_rect.height - 2 * self.margin,
        )
        self.text_rect = pygame.Rect(
            self.controls_rect.right + self.margin,
            self.margin,
            self.screen_rect.width - self.controls_rect.width - 3 * self.margin,
            self.screen_rect.height - 2 * self.margin,
        )

        home_size = max(40, int(self.tool_size * 0.85))
        self.home_button = Button(
            rect=pygame.Rect(
                self.screen_rect.right - self.margin - home_size,
                self.margin,
                home_size,
                home_size,
            ),
            fill=self.menu_bg,
        )

        inner_w = self.controls_rect.width - self.menu_pad * 2
        left = self.controls_rect.left + self.menu_pad
        top = self.controls_rect.top + self.menu_pad
        action_h = self.ui_font.get_height() + 16
        self.new_button = Button(
            rect=pygame.Rect(left, top, inner_w, action_h),
            label="New",
            fill=(245, 245, 245),
        )
        self.undo_button = Button(
            rect=pygame.Rect(left, self.new_button.rect.bottom + self.menu_gap, inner_w, action_h),
            label="Undo",
            fill=(245, 245, 245),
        )

        tri_gap = max(6, self.menu_gap // 2)
        tri_w = max(1, (inner_w - tri_gap * 2) // 3)
        size_top = self.undo_button.rect.bottom + self.menu_gap
        size_h = max(120, int(self.default_text_size * 4.8))
        self.size_buttons: Dict[int, Button] = {}
        for idx, size in enumerate(self.size_values):
            rect = pygame.Rect(left + idx * (tri_w + tri_gap), size_top, tri_w, size_h)
            self.size_buttons[size] = Button(rect=rect, fill=(245, 245, 245))

        style_top = size_top + size_h + self.menu_gap
        self.style_buttons: Dict[str, Button] = {}
        for idx, (style, label) in enumerate([("plain", "Plain"), ("bold", "Bold"), ("italic", "Italic")]):
            rect = pygame.Rect(left + idx * (tri_w + tri_gap), style_top, tri_w, action_h)
            self.style_buttons[style] = Button(rect=rect, label=label, fill=(245, 245, 245))

        recall_top = style_top + action_h + self.menu_gap
        recall_h = min(inner_w, max(80, self.controls_rect.bottom - self.menu_pad - recall_top))
        self.recall_button = Button(
            rect=pygame.Rect(left, recall_top, inner_w, recall_h),
            label="Recall",
            fill=self.menu_bg,
        )

        self.recall_open = False
        self.recall_items: List[RecallSession] = []
        self.recall_strip_rect = self.controls_rect.copy()
        self.recall_scroll_y = 0
        self.recall_max_scroll = 0
        self.recall_item_padding_x = 12
        self.recall_item_gap = 12
        self.recall_item_height = max(120, int(self.controls_rect.height * 0.2))
        self.recall_drag_last_y: Optional[int] = None
        self.recall_pressed_index: Optional[int] = None
        self.recall_drag_distance = 0
        self.pointer_down = False
        self.pointer_input = PointerInput()

        self._recall_overlay = pygame.Surface(self.screen_rect.size, pygame.SRCALPHA)
        self._recall_overlay.fill((0, 0, 0, 140))
        pygame.key.set_repeat(400, 30)

        self.text_pad_x = 24
        self.text_pad_top = 20
        self.line_gap = 6
        self.recall_button.image = self._build_recall_button_thumbnail()
        self._restore_current()

    def _handle_resume(self, reason: str) -> None:
        self.logger.info(f"Typing resume handling triggered: {reason}")
        self.pointer_input.reset()
        self.pointer_down = False
        self.recall_drag_last_y = None
        self.recall_pressed_index = None
        self.recall_drag_distance = 0
        pointer_events = [pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP]
        finger_down = getattr(pygame, "FINGERDOWN", None)
        finger_up = getattr(pygame, "FINGERUP", None)
        if finger_down is not None:
            pointer_events.append(finger_down)
        if finger_up is not None:
            pointer_events.append(finger_up)
        pygame.event.clear(pointer_events)

    def _get_font(self, size: int, style: str) -> pygame.font.Font:
        key = (size, style)
        cached = self.font_cache.get(key)
        if cached is not None:
            return cached
        font = _create_text_font(size, style)
        self.font_cache[key] = font
        return font

    def _line_text(self, row: int) -> str:
        return "".join(g.char for g in self.rich_lines[row])

    def _invalidate_layout(self) -> None:
        self._layout_revision = getattr(self, "_layout_revision", 0) + 1

    def _sync_text_line(self, row: int) -> None:
        self._invalidate_layout()
        self.text_lines[row] = self._line_text(row)

    def _sync_all_text_lines(self) -> None:
        self._invalidate_layout()
        self.text_lines = ["".join(g.char for g in line) for line in self.rich_lines]
        if not self.text_lines:
            self.text_lines = [""]
            self.rich_lines = [[]]
            self.line_styles = [self.default_line_style]
            return
        prior_styles = self.line_styles if hasattr(self, "line_styles") else []
        next_styles: List[Tuple[int, str]] = []
        for idx, line in enumerate(self.rich_lines):
            if line:
                last = line[-1]
                next_styles.append((last.size, last.style))
            elif idx < len(prior_styles):
                next_styles.append(prior_styles[idx])
            else:
                next_styles.append(self.default_line_style)
        self.line_styles = next_styles

    def _push_undo(self, op: EditOp) -> None:
        self.undo_stack.append(op)
        if len(self.undo_stack) > UNDO_MAX_DEPTH:
            self.undo_stack.pop(0)

    def _insert_newline_at(self, row: int, col: int) -> None:
        self._invalidate_layout()
        left = self.rich_lines[row][:col]
        right = self.rich_lines[row][col:]
        self.rich_lines[row] = left
        self.rich_lines.insert(row + 1, right)
        if left:
            self.line_styles[row] = (left[-1].size, left[-1].style)
        if right:
            right_style = (right[-1].size, right[-1].style)
        else:
            right_style = (self.current_text_size, self.text_style)
        self.line_styles.insert(row + 1, right_style)
        self.text_lines[row] = "".join(g.char for g in left)
        self.text_lines.insert(row + 1, "".join(g.char for g in right))

    def _remove_newline_at(self, row: int) -> None:
        if row + 1 >= len(self.rich_lines):
            return
        self._invalidate_layout()
        self.rich_lines[row].extend(self.rich_lines[row + 1])
        self.rich_lines.pop(row + 1)
        if len(self.line_styles) > row + 1:
            self.line_styles.pop(row + 1)
        if self.rich_lines[row]:
            last = self.rich_lines[row][-1]
            self.line_styles[row] = (last.size, last.style)
        self.text_lines[row] = "".join(g.char for g in self.rich_lines[row])
        self.text_lines.pop(row + 1)

    def _insert_glyph_at(self, row: int, col: int, glyph: Glyph) -> None:
        self.rich_lines[row].insert(col, Glyph(char=glyph.char, size=glyph.size, style=glyph.style))
        self.line_styles[row] = (glyph.size, glyph.style)
        self._sync_text_line(row)

    def _remove_glyph_at(self, row: int, col: int) -> Optional[Glyph]:
        if col < 0 or col >= len(self.rich_lines[row]):
            return None
        removed = self.rich_lines[row].pop(col)
        self._sync_text_line(row)
        return removed

    def _insert_char(self, char: str) -> None:
        if char == "\n":
            op = EditOp(
                kind="insert",
                row=self.cursor_row,
                col=self.cursor_col,
                newline=True,
                cursor_row=self.cursor_row,
                cursor_col=self.cursor_col,
            )
            self._insert_newline_at(self.cursor_row, self.cursor_col)
            self.cursor_row += 1
            self.cursor_col = 0
            self._push_undo(op)
            self._mark_cursor_x_target_dirty()
            return

        glyph = Glyph(char=char, size=self.current_text_size, style=self.text_style)
        op = EditOp(
            kind="insert",
            row=self.cursor_row,
            col=self.cursor_col,
            glyph=Glyph(char=glyph.char, size=glyph.size, style=glyph.style),
            cursor_row=self.cursor_row,
            cursor_col=self.cursor_col,
        )
        self._insert_glyph_at(self.cursor_row, self.cursor_col, glyph)
        self.cursor_col += 1
        self._push_undo(op)
        self._mark_cursor_x_target_dirty()

    def _delete_backward(self) -> EditOp | None:
        if self.cursor_row == 0 and self.cursor_col == 0:
            return None
        if self.cursor_col > 0:
            removed = self._remove_glyph_at(self.cursor_row, self.cursor_col - 1)
            if removed is None:
                return None
            op = EditOp(
                kind="delete",
                row=self.cursor_row,
                col=self.cursor_col - 1,
                glyph=Glyph(char=removed.char, size=removed.size, style=removed.style),
                cursor_row=self.cursor_row,
                cursor_col=self.cursor_col,
            )
            self.cursor_col -= 1
            self._mark_cursor_x_target_dirty()
            return op

        prev_len = len(self.rich_lines[self.cursor_row - 1])
        op = EditOp(
            kind="delete",
            row=self.cursor_row - 1,
            col=prev_len,
            newline=True,
            cursor_row=self.cursor_row,
            cursor_col=self.cursor_col,
        )
        self._remove_newline_at(self.cursor_row - 1)
        self.cursor_row -= 1
        self.cursor_col = prev_len
        self._mark_cursor_x_target_dirty()
        return op

    def _undo(self) -> None:
        if not self.undo_stack:
            return
        op = self.undo_stack.pop()
        if op.kind == "insert":
            if op.newline:
                self._remove_newline_at(op.row)
            else:
                self._remove_glyph_at(op.row, op.col)
        else:
            if op.newline:
                self._insert_newline_at(op.row, op.col)
            elif op.glyph is not None:
                self._insert_glyph_at(op.row, op.col, op.glyph)
        self.cursor_row = op.cursor_row
        self.cursor_col = op.cursor_col
        self._mark_cursor_x_target_dirty()

    def _record(self) -> dict:
        return {"version": 1, "rich_lines": _serialize_rich_lines(self.rich_lines),
                "cursor": [self.cursor_row, self.cursor_col],
                "size": self.current_text_size, "style": self.text_style}

    def _save_current(self) -> bool:
        if self._save_blocked:
            return False
        payload = json.dumps(self._record(), ensure_ascii=False).encode("utf-8")
        if payload == self._saved_payload:
            return True
        try:
            write_bytes(self.current_path, payload)
        except OSError:
            self.logger.exception("Typing current document save failed")
            return False
        self._saved_payload = payload
        return True

    def _restore_current(self) -> None:
        if not self.current_path.exists():
            return
        try:
            record = json.loads(self.current_path.read_text(encoding="utf-8"))
            if isinstance(record, dict) and record.get("version", 1) != 1:
                # Rollbacks must never classify a newer save as corrupt or
                # overwrite it. Continue this release's work in a named sidecar.
                fallback = self.typing_dir / "current-v1.json"
                self.logger.warning(
                    f"Unsupported typing document version at {self.current_path}; "
                    f"preserving it and using {fallback}"
                )
                if self.current_path == fallback:
                    self._save_blocked = True
                    return
                self.current_path = fallback
                self._restore_current()
                return
            restored = _deserialize_rich_lines(record.get("rich_lines"))
            if restored is None or record.get("version") != 1:
                raise ValueError("invalid current document")
            self.rich_lines = restored
            self._sync_all_text_lines()
            cursor = record.get("cursor", [0, 0])
            self.cursor_row = max(0, min(int(cursor[0]), len(restored) - 1))
            self.cursor_col = max(0, min(int(cursor[1]), len(restored[self.cursor_row])))
            size, style = record.get("size"), record.get("style")
            if size in self.size_values and style in {"plain", "bold", "italic"}:
                self.current_text_size, self.text_style = size, style
        except (OSError, ValueError, TypeError, AttributeError, IndexError):
            self.logger.exception("Preserving unreadable typing document")
            self.current_path.rename(self.typing_dir / f"corrupt-{time.time_ns()}.json")
            sync_directory(self.typing_dir)

    def _archive_session(self) -> bool:
        record = {
            "version": 1,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "rich_lines": _serialize_rich_lines(self.rich_lines),
        }
        payload = json.dumps(record, ensure_ascii=False).encode("utf-8")
        try:
            directory = self.typing_dir / "archive"
            options = self.config.get("typing", {})
            try:
                max_archives = max(0, int(options.get("max_archives", 200)))
                max_bytes = max(0, int(options.get("max_archive_bytes", 256 * 1024 * 1024)))
            except (TypeError, ValueError, OverflowError):
                max_archives, max_bytes = 200, 256 * 1024 * 1024
            # Archives are children's work, not a disposable cache. Refuse a
            # new archive at capacity, leaving New/Recall and current work intact.
            count, total_bytes = 0, len(payload)
            if self.sessions_path.exists():
                total_bytes += self.sessions_path.stat().st_size
            for archive in directory.glob("*.json"):
                count += 1
                total_bytes += archive.stat().st_size
                if count >= max_archives or total_bytes > max_bytes:
                    break
            if count >= max_archives or total_bytes > max_bytes:
                self.logger.warning("Typing archive capacity reached; keeping current document")
                return False
            if not has_archive_reserve(self.typing_dir, len(payload)):
                self.logger.warning("Typing archive reserve reached; keeping current document")
                return False
            directory.mkdir(exist_ok=True)
            sync_directory(self.typing_dir)
            write_bytes(directory / f"{time.time_ns()}.json", payload)
        except OSError:
            self.logger.warning("Typing session archive write failed")
            return False
        return True

    def _current_text(self) -> str:
        return "\n".join(self.text_lines).rstrip()

    def _clear_text(self) -> None:
        self._invalidate_layout()
        self.rich_lines = [[]]
        self.line_styles = [self.default_line_style]
        self.text_lines = [""]
        self.undo_stack = []
        self.cursor_row = 0
        self.cursor_col = 0
        self.cursor_x_target = 0
        self._cursor_x_target_dirty = False
        self.text_scroll_y = 0

    def _move_cursor_left(self) -> None:
        if self.cursor_col > 0:
            self.cursor_col -= 1
            self._mark_cursor_x_target_dirty()
            return
        if self.cursor_row > 0:
            self.cursor_row -= 1
            self.cursor_col = len(self.rich_lines[self.cursor_row])
            self._mark_cursor_x_target_dirty()

    def _move_cursor_right(self) -> None:
        line = self.rich_lines[self.cursor_row]
        if self.cursor_col < len(line):
            self.cursor_col += 1
            self._mark_cursor_x_target_dirty()
            return
        if self.cursor_row < len(self.rich_lines) - 1:
            self.cursor_row += 1
            self.cursor_col = 0
            self._mark_cursor_x_target_dirty()

    def _move_cursor_up(self) -> None:
        if self.cursor_row == 0:
            return
        self.cursor_row -= 1
        self.cursor_col = min(self.cursor_col, len(self.rich_lines[self.cursor_row]))

    def _move_cursor_down(self) -> None:
        if self.cursor_row >= len(self.rich_lines) - 1:
            return
        self.cursor_row += 1
        self.cursor_col = min(self.cursor_col, len(self.rich_lines[self.cursor_row]))

    def _move_cursor_home(self) -> None:
        self.cursor_col = 0
        self._mark_cursor_x_target_dirty()

    def _move_cursor_end(self) -> None:
        self.cursor_col = len(self.rich_lines[self.cursor_row])
        self._mark_cursor_x_target_dirty()

    def _move_cursor_page_up(self, lines: int) -> None:
        if self.cursor_row == 0:
            return
        self.cursor_row = max(0, self.cursor_row - lines)
        self.cursor_col = min(self.cursor_col, len(self.rich_lines[self.cursor_row]))

    def _move_cursor_page_down(self, lines: int) -> None:
        if self.cursor_row >= len(self.rich_lines) - 1:
            return
        self.cursor_row = min(len(self.rich_lines) - 1, self.cursor_row + lines)
        self.cursor_col = min(self.cursor_col, len(self.rich_lines[self.cursor_row]))

    def _build_recall_button_thumbnail(self) -> pygame.Surface:
        size = self.recall_button.rect.size
        thumb = pygame.Surface((max(1, size[0] - 6), max(1, size[1] - 6)))
        thumb.fill((248, 248, 248))
        pygame.draw.rect(thumb, (120, 120, 120), thumb.get_rect(), width=2)
        preview_font = pygame.font.SysFont("sans", max(14, self.ui_font.get_height() - 2))
        message = "I'm Rosie's ToddlerBox. Touch here to see what you've written."
        max_width = thumb.get_width() - 16
        words = message.split(" ")
        lines: List[str] = []
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if preview_font.size(candidate)[0] <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        y = 10
        for line in lines:
            if y + preview_font.get_height() > thumb.get_height() - 8:
                break
            surf = preview_font.render(line, True, (40, 40, 40))
            thumb.blit(surf, (8, y))
            y += preview_font.get_height() + 4
        return thumb

    def _line_step(self) -> int:
        return self.current_text_size + self.line_gap

    def _lines_per_page(self) -> int:
        return max(1, self._view_height() // self._line_step())

    def _view_height(self) -> int:
        return max(1, self.text_rect.height - (self.text_pad_top + 20))

    def _content_height(self, lines: List[VisualLine]) -> int:
        if not lines:
            return 0
        total = sum(line.height + self.line_gap for line in lines)
        return max(0, total - self.line_gap)

    def _tokenize_row(self, glyphs: List[Glyph], widths: List[int]) -> List[_Token]:
        if not glyphs:
            return []
        tokens: List[_Token] = []
        start = 0
        current_space = glyphs[0].char.isspace()
        for idx, glyph in enumerate(glyphs):
            is_space = glyph.char.isspace()
            if is_space != current_space:
                tokens.append(_Token(start=start, end=idx, widths=widths[start:idx], is_space=current_space))
                start = idx
                current_space = is_space
        tokens.append(_Token(start=start, end=len(glyphs), widths=widths[start:], is_space=current_space))
        return tokens

    def _visual_line_height(self, row: int, glyphs: List[Glyph]) -> int:
        if not glyphs:
            return self._line_font_height(row, for_cursor_row=(row == self.cursor_row))
        return max(self._get_font(g.size, g.style).get_height() for g in glyphs)

    def _build_visual_lines(self) -> List[VisualLine]:
        max_width = max(1, self.text_rect.width - self.text_pad_x * 2)
        # Only an empty row's height depends on the insertion style/cursor.
        empty_cursor_row = self.cursor_row if not self.rich_lines[self.cursor_row] else None
        key = (getattr(self, "_layout_revision", 0), max_width,
               self.current_text_size, self.text_style, empty_cursor_row)
        if key == getattr(self, "_layout_key", None):
            return self._visual_lines
        lines: List[VisualLine] = []
        for row_idx, row in enumerate(self.rich_lines):
            if not row:
                height = self._visual_line_height(row_idx, [])
                lines.append(
                    VisualLine(
                        row=row_idx,
                        start_col=0,
                        end_col=0,
                        glyphs=[],
                        widths=[],
                        height=height,
                    )
                )
                continue
            row_widths = [self._get_font(g.size, g.style).size(g.char)[0] for g in row]
            tokens = self._tokenize_row(row, row_widths)
            ranges = _wrap_tokens(tokens, max_width)
            for start, end in ranges:
                glyphs = row[start:end]
                widths = row_widths[start:end]
                height = self._visual_line_height(row_idx, glyphs)
                lines.append(
                    VisualLine(
                        row=row_idx,
                        start_col=start,
                        end_col=end,
                        glyphs=glyphs,
                        widths=widths,
                        height=height,
                    )
                )
        if not lines:
            height = self._visual_line_height(self.cursor_row, [])
            lines.append(VisualLine(row=self.cursor_row, start_col=0, end_col=0, glyphs=[], widths=[], height=height))
        self._visual_lines = lines
        self._layout_key = key
        return lines

    def _cursor_x_offset_in_line(self, line: VisualLine, cursor_col: int) -> int:
        if not line.widths:
            return 0
        if cursor_col <= line.start_col:
            return 0
        if cursor_col >= line.end_col:
            return sum(line.widths)
        offset = 0
        upto = cursor_col - line.start_col
        for width in line.widths[:upto]:
            offset += width
        return offset

    def _cursor_visual_info(self, lines: List[VisualLine]) -> Tuple[int, int, int, int]:
        content_y = 0
        fallback_idx: Optional[int] = None
        fallback_y = 0
        for idx, line in enumerate(lines):
            if line.row == self.cursor_row:
                if fallback_idx is None:
                    fallback_idx = idx
                    fallback_y = content_y
                if self.cursor_col < line.start_col or self.cursor_col > line.end_col:
                    content_y += line.height + self.line_gap
                    continue
                if self.cursor_col == line.end_col and line.glyphs and idx + 1 < len(lines):
                    next_line = lines[idx + 1]
                    if next_line.row == self.cursor_row and next_line.start_col == self.cursor_col:
                        content_y += line.height + self.line_gap
                        continue
                x_offset = self._cursor_x_offset_in_line(line, self.cursor_col)
                return idx, content_y, line.height, x_offset
            content_y += line.height + self.line_gap
        if fallback_idx is None:
            fallback_idx = 0
            fallback_y = 0
        line = lines[fallback_idx]
        x_offset = self._cursor_x_offset_in_line(line, min(self.cursor_col, line.end_col))
        return fallback_idx, fallback_y, line.height, x_offset

    def _ensure_cursor_visible(self, lines: List[VisualLine], cursor_info: Tuple[int, int, int, int]) -> None:
        view_height = self._view_height()
        content_height = self._content_height(lines)
        max_scroll = max(0, content_height - view_height)
        if content_height <= view_height:
            self.text_scroll_y = 0
            return
        _, cursor_top, cursor_h, _ = cursor_info
        view_top = self.text_scroll_y
        view_bottom = view_top + view_height
        cursor_bottom = cursor_top + cursor_h
        if cursor_bottom > view_bottom:
            self.text_scroll_y = cursor_bottom - view_height
        elif cursor_top < view_top:
            self.text_scroll_y = cursor_top
        self.text_scroll_y = max(0, min(max_scroll, self.text_scroll_y))

    def _mark_cursor_x_target_dirty(self) -> None:
        self._cursor_x_target_dirty = True

    def _maybe_update_cursor_x_target(self, cursor_info: Tuple[int, int, int, int]) -> None:
        if self.cursor_x_target is None or self._cursor_x_target_dirty:
            self.cursor_x_target = cursor_info[3]
            self._cursor_x_target_dirty = False

    def _col_for_x(self, line: VisualLine, target_x: int) -> int:
        if not line.widths:
            return line.start_col
        x = 0.0
        for idx, width in enumerate(line.widths):
            if target_x <= x + (width / 2):
                return line.start_col + idx
            x += width
        return line.end_col

    def _move_cursor_up_visual(self, lines: List[VisualLine]) -> None:
        if not lines:
            return
        idx, _, _, x_offset = self._cursor_visual_info(lines)
        if self.cursor_x_target is None:
            self.cursor_x_target = x_offset
        if idx == 0:
            return
        target = lines[idx - 1]
        self.cursor_row = target.row
        self.cursor_col = self._col_for_x(target, self.cursor_x_target or 0)

    def _move_cursor_down_visual(self, lines: List[VisualLine]) -> None:
        if not lines:
            return
        idx, _, _, x_offset = self._cursor_visual_info(lines)
        if self.cursor_x_target is None:
            self.cursor_x_target = x_offset
        if idx >= len(lines) - 1:
            return
        target = lines[idx + 1]
        self.cursor_row = target.row
        self.cursor_col = self._col_for_x(target, self.cursor_x_target or 0)

    def _set_text_font(self, *, size: Optional[int] = None, style: Optional[str] = None) -> None:
        if size is not None:
            self.current_text_size = size
        if style is not None:
            self.text_style = style

    def _line_font_height(self, row: int, *, for_cursor_row: bool = False) -> int:
        line = self.rich_lines[row]
        if not line:
            if for_cursor_row:
                return self._get_font(self.current_text_size, self.text_style).get_height()
            size, style = self.line_styles[row]
            return self._get_font(size, style).get_height()
        return max(self._get_font(g.size, g.style).get_height() for g in line)

    def _open_recall(self) -> None:
        self.recall_strip_rect = self.controls_rect.copy()
        self.recall_items = [
            RecallSession(
                label="Current",
                preview=_preview_text(self._current_text()),
                rich_lines=_clone_rich_lines(self.rich_lines),
                is_current=True,
            )
        ]
        self.recall_items.extend(_load_recent_sessions(self.sessions_path))
        self.recall_scroll_y = 0
        self.recall_drag_last_y = None
        self.recall_pressed_index = None
        self.recall_drag_distance = 0
        self.recall_max_scroll = self._recall_max_scroll()
        self.recall_open = True

    def _recall_max_scroll(self) -> int:
        total_height = len(self.recall_items) * (self.recall_item_height + self.recall_item_gap) + self.recall_item_gap
        return max(0, total_height - self.recall_strip_rect.height)

    def _scroll_recall(self, delta: int) -> None:
        self.recall_scroll_y = max(0, min(self.recall_max_scroll, self.recall_scroll_y + delta))

    def _recall_item_rect(self, index: int) -> pygame.Rect:
        y = self.recall_item_gap - self.recall_scroll_y + index * (self.recall_item_height + self.recall_item_gap)
        return pygame.Rect(
            self.recall_strip_rect.left + self.recall_item_padding_x,
            self.recall_strip_rect.top + y,
            self.recall_strip_rect.width - self.recall_item_padding_x * 2,
            self.recall_item_height,
        )

    def _recall_index_at_pos(self, pos: Tuple[int, int]) -> Optional[int]:
        for idx, _ in enumerate(self.recall_items):
            if self._recall_item_rect(idx).collidepoint(pos):
                return idx
        return None

    def _apply_recall(self, index: int) -> None:
        item = self.recall_items[index]
        if item.is_current:
            self.recall_open = False
            return
        if not self._archive_session():
            return
        self.rich_lines = _clone_rich_lines(item.rich_lines)
        self._sync_all_text_lines()
        self.undo_stack = []
        self.cursor_row = max(0, len(self.rich_lines) - 1)
        self.cursor_col = len(self.rich_lines[self.cursor_row]) if self.rich_lines else 0
        self.cursor_x_target = None
        self._cursor_x_target_dirty = True
        self.text_scroll_y = 0
        self.recall_open = False
        self._save_current()

    def _wrap_preview_lines(self, text: str, max_width: int, max_lines: int) -> List[str]:
        if not text:
            return ["(empty)"]
        words = text.split(" ")
        if not words:
            return ["(empty)"]
        lines: List[str] = []
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if self.ui_font.size(candidate)[0] <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
        if len(lines) < max_lines and current:
            lines.append(current)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        return lines

    def _handle_recall_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.recall_open = False
            return
        if is_primary_pointer_event(event, is_down=True):
            if self.pointer_down:
                return
            pos = pointer_event_pos(event, self.screen_rect)
            if pos is None:
                return
            self.pointer_down = True
            if not self.recall_strip_rect.collidepoint(pos):
                self.recall_open = False
                self.pointer_down = False
                self.recall_drag_last_y = None
                self.recall_pressed_index = None
                self.recall_drag_distance = 0
                return
            self.recall_drag_last_y = pos[1]
            self.recall_pressed_index = self._recall_index_at_pos(pos)
            self.recall_drag_distance = 0
            return
        if is_primary_pointer_event(event, is_down=False):
            if not self.pointer_down:
                return
            self.pointer_down = False
            pos = pointer_event_pos(event, self.screen_rect)
            if pos is None:
                self.recall_drag_last_y = None
                self.recall_pressed_index = None
                self.recall_drag_distance = 0
                return
            if (
                self.recall_pressed_index is not None
                and self.recall_drag_distance < DRAG_THRESHOLD
                and self._recall_index_at_pos(pos) == self.recall_pressed_index
            ):
                self._apply_recall(self.recall_pressed_index)
            self.recall_drag_last_y = None
            self.recall_pressed_index = None
            self.recall_drag_distance = 0
            return
        if event.type == pygame.MOUSEMOTION and self.recall_drag_last_y is not None:
            dy = event.pos[1] - self.recall_drag_last_y
            self._scroll_recall(-dy)
            self.recall_drag_distance += abs(dy)
            self.recall_drag_last_y = event.pos[1]
            return
        if FINGERMOTION is not None and event.type == FINGERMOTION and self.pointer_down:
            current_y = int(event.y * self.screen_rect.height)
            if self.recall_drag_last_y is None:
                self.recall_drag_last_y = current_y
            dy = current_y - self.recall_drag_last_y
            self._scroll_recall(-dy)
            self.recall_drag_distance += abs(dy)
            self.recall_drag_last_y = current_y
            return
        if event.type == pygame.MOUSEWHEEL:
            if self.recall_strip_rect.collidepoint(pygame.mouse.get_pos()):
                self._scroll_recall(-event.y * SCROLL_STEP)
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button in {4, 5}:
            if self.recall_strip_rect.collidepoint(event.pos):
                self._scroll_recall(-SCROLL_STEP if event.button == 4 else SCROLL_STEP)

    def _draw_recall_overlay(self) -> None:
        self.screen.blit(self._recall_overlay, (0, 0))
        pygame.draw.rect(self.screen, (230, 230, 230), self.recall_strip_rect)

        preview_x_pad = 10
        preview_y_pad = 10
        for idx, item in enumerate(self.recall_items):
            rect = self._recall_item_rect(idx)
            if rect.bottom < self.recall_strip_rect.top or rect.top > self.recall_strip_rect.bottom:
                continue
            pygame.draw.rect(self.screen, (248, 248, 248), rect)
            border = (200, 60, 60) if item.is_current else (120, 120, 120)
            pygame.draw.rect(self.screen, border, rect, width=3 if item.is_current else 2)

            label_surface = self.ui_font.render(item.label, True, (30, 30, 30))
            self.screen.blit(label_surface, (rect.left + preview_x_pad, rect.top + preview_y_pad))

            preview_top = rect.top + preview_y_pad + self.ui_font.get_height() + 6
            max_width = rect.width - preview_x_pad * 2
            available_height = rect.bottom - preview_top - preview_y_pad
            line_step = self.ui_font.get_height() + 4
            max_lines = max(1, available_height // line_step)
            lines = self._wrap_preview_lines(item.preview, max_width, max_lines)
            for line_idx, line in enumerate(lines):
                y = preview_top + line_idx * line_step
                if y + self.ui_font.get_height() > rect.bottom - preview_y_pad:
                    break
                line_surface = self.ui_font.render(line, True, (40, 40, 40))
                self.screen.blit(line_surface, (rect.left + preview_x_pad, y))

    def _render(self) -> None:
        self.screen.fill((248, 248, 248))

        pygame.draw.rect(self.screen, self.menu_bg, self.controls_rect)
        pygame.draw.rect(self.screen, (255, 255, 255), self.text_rect)
        pygame.draw.rect(self.screen, (200, 200, 200), self.text_rect, width=2)

        draw_home_button(self.screen, self.home_button.rect)
        self.new_button.draw(self.screen, self.ui_font)
        self.undo_button.draw(self.screen, self.ui_font)
        for size, button in self.size_buttons.items():
            button.draw(self.screen)
            sample = self.size_sample_fonts[size].render("A", True, (25, 25, 25))
            sample_rect = sample.get_rect(center=button.rect.center)
            self.screen.blit(sample, sample_rect)
            if size == self.current_text_size:
                pygame.draw.rect(self.screen, (200, 60, 60), button.rect, width=3, border_radius=12)
        for style, button in self.style_buttons.items():
            button.draw(self.screen, self.ui_font)
            if style == self.text_style:
                pygame.draw.rect(self.screen, (200, 60, 60), button.rect, width=3, border_radius=12)
        if self.recall_button.image is None:
            self.recall_button.draw(self.screen, self.ui_font)
        else:
            self.recall_button.draw(self.screen)

        visual_lines = self._build_visual_lines()
        cursor_info = self._cursor_visual_info(visual_lines)
        self._maybe_update_cursor_x_target(cursor_info)
        self._ensure_cursor_visible(visual_lines, cursor_info)

        text_x = self.text_rect.left + self.text_pad_x
        view_top = self.text_rect.top + self.text_pad_top
        view_bottom = view_top + self._view_height()
        _, cursor_content_y, cursor_h, cursor_x_offset = cursor_info
        cursor_x = text_x + cursor_x_offset
        cursor_y = view_top - self.text_scroll_y + cursor_content_y

        content_y = 0
        for idx, line in enumerate(visual_lines):
            y = view_top - self.text_scroll_y + content_y
            if y + line.height >= view_top and y <= view_bottom:
                x = text_x
                for glyph, glyph_w in zip(line.glyphs, line.widths):
                    font = self._get_font(glyph.size, glyph.style)
                    surf = font.render(glyph.char, True, (20, 20, 20))
                    glyph_y = y + (line.height - font.get_height())
                    self.screen.blit(surf, (x, glyph_y))
                    x += glyph_w
            content_y += line.height + self.line_gap

        pygame.draw.rect(self.screen, (30, 30, 30), (cursor_x, cursor_y, 6, cursor_h))

        if self.recall_open:
            self._draw_recall_overlay()

        pygame.display.flip()

    def run(self, *, quit_on_exit: bool = True) -> None:
        try:
            self._run()
        finally:
            self._save_current()
            if quit_on_exit:
                pygame.quit()

    def _run(self) -> None:
        running = True
        self._render()
        last_frame_time = time.monotonic()
        while running and not health.stopping():
            now = time.monotonic()
            if now - last_frame_time > 2.0:
                self._handle_resume("frame-time gap")
            last_frame_time = now
            ignore_remaining_input = False
            for event in pygame.event.get():
                if event.type in {WINDOW_FOCUS_GAINED, APP_DID_ENTER_FOREGROUND}:
                    self._handle_resume("focus/background event")
                    # Clear cannot remove input already fetched in this batch.
                    ignore_remaining_input = True
                    continue
                if event.type == pygame.QUIT:
                    running = not self._save_current()
                    if not running:
                        break
                if ignore_remaining_input:
                    continue
                if not self.pointer_input.accept(event):
                    continue
                if self.recall_open:
                    self._handle_recall_event(event)
                    continue
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = not self._save_current()
                    elif event.key == pygame.K_BACKSPACE:
                        op = self._delete_backward()
                        if op:
                            self._push_undo(op)
                    elif event.key == pygame.K_RETURN:
                        self._insert_char("\n")
                    elif event.key in {
                        pygame.K_LEFT,
                        pygame.K_RIGHT,
                        pygame.K_UP,
                        pygame.K_DOWN,
                        pygame.K_HOME,
                        pygame.K_END,
                        pygame.K_PAGEUP,
                        pygame.K_PAGEDOWN,
                    }:
                        if event.mod & (pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META | pygame.KMOD_GUI):
                            continue
                        if event.key == pygame.K_LEFT:
                            self._move_cursor_left()
                        elif event.key == pygame.K_RIGHT:
                            self._move_cursor_right()
                        elif event.key == pygame.K_UP:
                            self._move_cursor_up_visual(self._build_visual_lines())
                        elif event.key == pygame.K_DOWN:
                            self._move_cursor_down_visual(self._build_visual_lines())
                        elif event.key == pygame.K_HOME:
                            self._move_cursor_home()
                        elif event.key == pygame.K_END:
                            self._move_cursor_end()
                        elif event.key == pygame.K_PAGEUP:
                            self._move_cursor_page_up(self._lines_per_page())
                        elif event.key == pygame.K_PAGEDOWN:
                            self._move_cursor_page_down(self._lines_per_page())
                    elif event.key in {pygame.K_LCTRL, pygame.K_RCTRL, pygame.K_LALT, pygame.K_RALT}:
                        continue
                    elif event.mod & (pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META | pygame.KMOD_GUI):
                        continue
                    else:
                        if event.unicode and event.unicode.isprintable():
                            self._insert_char(event.unicode)
                elif is_primary_pointer_event(event, is_down=True):
                    pos = pointer_event_pos(event, self.screen_rect)
                    if pos is None:
                        continue
                    if self.home_button.hit(pos):
                        running = not self._save_current()
                    elif self.new_button.hit(pos):
                        if self._archive_session():
                            self._clear_text()
                            self._save_current()
                    elif self.undo_button.hit(pos):
                        self._undo()
                    elif self.recall_button.hit(pos):
                        self._open_recall()
                    else:
                        handled = False
                        for size, button in self.size_buttons.items():
                            if button.hit(pos):
                                self._set_text_font(size=size)
                                handled = True
                                break
                        if handled:
                            continue
                        for style, button in self.style_buttons.items():
                            if button.hit(pos):
                                self._set_text_font(style=style)
                                handled = True
                                break
                        if handled:
                            continue
                if not running:
                    break

            if time.monotonic() - self.last_autosave >= self.autosave_interval:
                self._save_current()
                self.last_autosave = time.monotonic()
            self._render()
            health.frame_complete()
            self.clock.tick(60)


def main() -> None:
    try:
        TypingApp().run(quit_on_exit=True)
    except Exception:
        logger = get_runtime_logger(get_data_root(load_config()))
        logger.exception("Typing app crashed in main()")
        pygame.quit()


def run_embedded(screen: pygame.Surface, screen_rect: pygame.Rect, clock: pygame.time.Clock) -> None:
    TypingApp(screen=screen, screen_rect=screen_rect, clock=clock).run(quit_on_exit=False)


if __name__ == "__main__":
    main()
