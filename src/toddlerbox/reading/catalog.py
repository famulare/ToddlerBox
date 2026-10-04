from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import wave

from PIL import Image

RATE = 44100
WORD_SETS = frozenset({"short_a_cvc", "short_e_cvc", "short_i_cvc", "short_o_cvc",
                       "short_u_cvc", "digraphs", "adjacent_consonants"})


@dataclass(frozen=True)
class Options:
    mode: str = "words"
    word_sets: tuple[str, ...] = ("short_a_cvc", "short_e_cvc", "short_i_cvc", "short_o_cvc",
                                  "short_u_cvc", "digraphs", "adjacent_consonants")
    letter_case: str = "lowercase"
    letter_audio: str = "sounds"
    volume: float = 0.35


def options_from_config(config: dict, logger) -> Options:
    raw = config.get("reading", {})
    if not isinstance(raw, dict):
        logger.info("Invalid Reading configuration; using defaults")
        return Options()
    defaults = Options()
    result = {}
    for key, allowed in {"mode": {"words", "letters"},
                         "letter_case": {"lowercase", "uppercase"},
                         "letter_audio": {"sounds", "names"}}.items():
        value = raw.get(key, getattr(defaults, key))
        result[key] = value if isinstance(value, str) and value in allowed else getattr(defaults, key)
        if result[key] != value:
            logger.info(f"Invalid Reading {key}; using default")
    tags = raw.get("word_sets", list(defaults.word_sets))
    if not isinstance(tags, list) or not tags or any(not isinstance(t, str) or t not in WORD_SETS for t in tags):
        logger.info("Invalid Reading word sets; using default word sets")
        tags = defaults.word_sets
    result["word_sets"] = tuple(dict.fromkeys(tags))
    volume = raw.get("volume", defaults.volume)
    if type(volume) not in (int, float) or not math.isfinite(volume):
        logger.info("Invalid Reading volume; using default")
        volume = defaults.volume
    result["volume"] = max(0.0, min(1.0, volume))
    return Options(**result)


@dataclass(frozen=True)
class Cue:
    start: int
    end: int
    unit: int  # -1 highlights the complete word.


@dataclass(frozen=True)
class Speech:
    path: Path
    frames: int
    cues: tuple[Cue, ...]
    start_frame: int = 0  # A bounded slice of validated PCM for a deliberate sound tap.

    @property
    def duration_ms(self) -> float:
        return self.frames * 1000 / RATE


@dataclass(frozen=True)
class Card:
    id: str
    kind: str
    text: str
    units: tuple[str, ...]
    image: Path | None
    sequence: Speech
    replay: Speech
    tags: tuple[str, ...] = ()
    letter_audio: str = ""


def _integer(value, low, high) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Reading integer outside bounds")
    return value


def _asset(root: Path, name: str, max_bytes: int) -> Path:
    if not isinstance(name, str) or not name or len(name) > 160:
        raise ValueError("Invalid Reading asset name")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or not 0 < path.stat().st_size <= max_bytes:
        raise ValueError("Invalid or oversized Reading asset")
    return path


def _speech(root: Path, entry: dict, unit_count: int) -> Speech:
    path = _asset(root, entry["path"], 2_000_000)
    frames = _integer(entry["frames"], 1000, RATE * 12)
    with wave.open(str(path), "rb") as audio:
        if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getnframes()) != (RATE, 1, 2, frames):
            raise ValueError("Unexpected Reading audio format")
        # Header lengths alone cannot detect a truncated payload.
        if len(audio.readframes(frames)) != frames * 2:
            raise ValueError("Truncated Reading audio")
    rows = entry["cues"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10:
        raise ValueError("Invalid Reading cue list")
    cues = []
    previous = 0
    for row in rows:
        start = _integer(row["start"], previous, frames - 1)
        end = _integer(row["end"], start + 1, frames)
        unit = _integer(row["unit"], -1, unit_count - 1)
        cues.append(Cue(start, end, unit))
        previous = end
    return Speech(path, frames, tuple(cues))


def load_catalog(root: Path, options: Options, logger) -> list[Card]:
    """Validate a bounded offline pack; isolate corrupt cards without dialogs."""
    try:
        path = root / "catalog.json"
        if path.stat().st_size > 2_000_000:
            raise ValueError("Oversized Reading catalog")
        catalog = json.loads(path.read_text())
        entries = catalog["cards"]
        if type(catalog["schema_version"]) is not int or catalog["schema_version"] != 1 or type(catalog["sample_rate"]) is not int or catalog["sample_rate"] != RATE:
            raise ValueError("Unsupported Reading catalog")
        if not isinstance(entries, list) or len(entries) > 256:
            raise ValueError("Invalid Reading collection")
    except (OSError, ValueError, TypeError, KeyError):
        logger.exception("Reading catalog unavailable")
        return []
    cards = []
    seen = set()
    for entry in entries:
        try:
            identity, kind, text = entry["id"], entry["kind"], entry["text"]
            if not isinstance(identity, str) or not 1 <= len(identity) <= 80 or identity in seen:
                raise ValueError("Duplicate or invalid Reading identity")
            seen.add(identity)
            if kind not in {"words", "letters"} or not isinstance(text, str) or not 1 <= len(text) <= 12:
                raise ValueError("Invalid Reading card")
            units = entry["units"]
            if not isinstance(units, list) or not 1 <= len(units) <= 8 or any(not isinstance(u, str) or not u for u in units) or "".join(units) != text:
                raise ValueError("Reading sound units do not cover text")
            tags = entry.get("sets", [])
            if not isinstance(tags, list) or any(not isinstance(t, str) or t not in WORD_SETS for t in tags):
                raise ValueError("Invalid Reading word sets")
            variant = entry.get("letter_audio", "")
            if kind == "letters" and variant not in {"sounds", "names"}:
                raise ValueError("Invalid Reading letter audio")
            if kind != options.mode:
                continue
            if kind == "words" and not set(tags).intersection(options.word_sets):
                continue
            if kind == "letters" and variant != options.letter_audio:
                continue
            image = _asset(root, entry["image"], 2_000_000)
            with Image.open(image) as art:
                if art.format != "PNG" or not (1 <= art.width <= 1024 and 1 <= art.height <= 1024):
                    raise ValueError("Oversized Reading illustration")
                art.verify()
            cards.append(Card(identity, kind, text, tuple(units), image,
                              _speech(root, entry["sequence"], len(units)),
                              _speech(root, entry["replay"], len(units)), tuple(tags), variant))
        except (OSError, ValueError, TypeError, KeyError, wave.Error, EOFError, Image.DecompressionBombError):
            logger.exception("Skipping damaged Reading card")
    return cards
