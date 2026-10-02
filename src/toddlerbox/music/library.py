from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Note:
    pitch: int
    start_ms: float
    duration_ms: float
    voice: str

    @property
    def end_ms(self) -> float:
        return self.start_ms + self.duration_ms


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    audio: Path
    duration_ms: float
    notes: tuple[Note, ...]


def _asset(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Music asset path leaves the library")
    return path


def load_library(root: Path, logger) -> tuple[list[Track], int, int]:
    """Read a bounded, versioned collection; isolate a damaged song."""
    try:
        catalog = json.loads((root / "catalog.json").read_text())
        if catalog["schema_version"] != 1:
            raise ValueError("Unsupported music catalog")
        low, high = int(catalog["keyboard_low"]), int(catalog["keyboard_high"])
        if not (24 <= low < high <= 96 and 12 <= high - low <= 36):
            raise ValueError("Invalid keyboard range")
        entries = catalog["tracks"]
        if not isinstance(entries, list) or len(entries) > 12:
            raise ValueError("Invalid music collection size")
    except (OSError, ValueError, KeyError, TypeError):
        logger.exception("Music catalog is unavailable")
        return [], 48, 72
    tracks = []
    seen = set()
    for entry in entries:
        try:
            cues = json.loads(_asset(root, entry["cues"]).read_text())
            duration = float(cues["duration_ms"])
            if cues["schema_version"] != 1 or cues["id"] != entry["id"]:
                raise ValueError("Mismatched music cues")
            if entry["id"] in seen or not 1000 <= duration <= 180_000:
                raise ValueError("Invalid track identity or duration")
            if not isinstance(cues["notes"], list) or len(cues["notes"]) > 4096:
                raise ValueError("Too many music notes")
            notes = []
            for item in cues["notes"]:
                pitch = int(item["pitch"])
                start, length = float(item["start_ms"]), float(item["duration_ms"])
                if not (low <= pitch <= high and math.isfinite(start) and math.isfinite(length)
                        and start >= 0 and length > 0 and start + length <= duration):
                    raise ValueError("Music note outside track bounds")
                notes.append(Note(pitch, start, length, str(item.get("voice", "melody"))))
            tracks.append(Track(str(entry["id"]), str(entry["title"])[:80],
                                _asset(root, entry["audio"]), duration,
                                tuple(sorted(notes, key=lambda note: note.start_ms))))
            seen.add(entry["id"])
        except (OSError, ValueError, KeyError, TypeError):
            logger.exception("Skipping damaged Music track")
    return tracks, low, high
