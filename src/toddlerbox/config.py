from __future__ import annotations

import copy
import os
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

STANDARD_ORDER = ("Paint", "Photos", "Music", "Typing", "Reading", "Math")
MATH_ENTRY = {"name": "Math", "icon_path": "assets/icons/math/math.png",
              "command": "python -m toddlerbox.math"}


def _standard_profile(nested_icons=False):
    """Exact historical shipped entries, not a heuristic based on app names."""
    entries = []
    for name in ("Paint", "Photos", "Typing", "Music", "Reading"):
        key = name.lower()
        path = (f"assets/icons/{key}/{key}_512.png" if nested_icons else f"assets/icons/{key}.png")
        if name in ("Music", "Reading"):
            path = f"assets/icons/{key}/{key}.png"
        entries.append({"name": name, "icon_path": path, "command": f"python -m toddlerbox.{key}"})
    return entries


def _with_math_standard_layout(apps):
    if apps == _standard_profile() or apps == _standard_profile(nested_icons=True):
        entries = {entry["name"]: entry for entry in apps}
        entries["Math"] = dict(MATH_ENTRY)
        return [dict(entries[name]) for name in STANDARD_ORDER]
    return apps  # Custom commands, ordering, paths and explicit omissions stay intact.

DEFAULT_CONFIG: Dict[str, Any] = {
    "audio": {"startup_volume": 0.80},
    "data_root": "/data",
    "launcher": {
        "apps": [
            {
                "name": "Paint",
                "icon_path": "assets/icons/paint/paint_512.png",
                "command": "python -m toddlerbox.paint",
            },
            {
                "name": "Photos",
                "icon_path": "assets/icons/photos/photos_512.png",
                "command": "python -m toddlerbox.photos",
            },
            {
                "name": "Typing",
                "icon_path": "assets/icons/typing/typing_512.png",
                "command": "python -m toddlerbox.typing",
            },
            {
                "name": "Music",
                "icon_path": "assets/icons/music/music.png",
                "command": "python -m toddlerbox.music",
            },
            {
                "name": "Reading",
                "icon_path": "assets/icons/reading/reading.png",
                "command": "python -m toddlerbox.reading",
            },
        ]
    },
    "paint": {
        "autosave_seconds": 10,
        "palette": [
            [0, 0, 0],
            [255, 255, 255],
            [220, 20, 60],
            [255, 127, 0],
            [255, 215, 0],
            [34, 139, 34],
            [0, 128, 128],
            [30, 144, 255],
            [65, 105, 225],
            [138, 43, 226],
            [255, 105, 180],
            [210, 105, 30],
            [105, 105, 105],
            [0, 191, 255],
            [154, 205, 50],
            [255, 99, 71],
        ],
    },
    "music": {"volume": 1.0, "autoplay": True, "latency_ms": 0},
    "reading": {"mode": "words", "word_sets": ["short_a_cvc", "short_e_cvc", "short_i_cvc", "short_o_cvc",
                                               "short_u_cvc", "digraphs", "adjacent_consonants"], "letter_case": "lowercase",
                "letter_audio": "sounds", "volume": 0.70},
    "math": {"mode": "numbers", "max_number": 100, "low_number_weight": 12, "volume": 0.70},
}
DEFAULT_CONFIG["launcher"]["apps"] = _with_math_standard_layout(DEFAULT_CONFIG["launcher"]["apps"])


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _candidate_config_paths() -> list[Path]:
    env_path = os.environ.get("KIDBOX_CONFIG")
    if env_path:
        # The appliance names its file: never fall back to a development config.
        return [Path(env_path)]
    return [Path("config.yaml"), Path("/opt/toddlerbox/config.yaml")]


_SECTIONS = ("audio", "launcher", "paint", "photos", "typing", "music", "reading", "math")
# Values whose consumers call int() directly. Keep exactly the conversion they
# always accepted ("30", 12.5, true); replace only what would raise. Other values
# (volumes, latency, archive caps, booleans) are validated by their own readers.
_INTEGERS = (("launcher", "photos_prewarm_idle_ms"), ("launcher", "photos_prewarm_batch"),
             ("paint", "autosave_seconds"), ("typing", "autosave_seconds"), ("photos", "thumb_cache_limit"))
_last_errors: List[str] = []


def _read(path: Path, errors: List[str]) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except Exception as error:
        errors.append(f"{path}: unreadable ({type(error).__name__}: {error}); using built-in defaults")
        return None
    if data is None:
        return {}
    if not isinstance(data, dict):
        errors.append(f"{path}: top level must be a mapping; using built-in defaults")
        return None
    return data


def _command_ok(command: Any) -> bool:
    # Only what used to raise is refused; other odd commands still give an inert tile.
    if not isinstance(command, str):
        return True
    try:
        shlex.split(command)
        return True
    except ValueError:
        return False


def _valid_apps(apps: Any, errors: List[str]) -> Optional[list]:
    if not isinstance(apps, list):
        errors.append("launcher.apps must be a list; using the standard activities")
        return None
    valid = []
    for index, entry in enumerate(apps):
        if isinstance(entry, dict) and _command_ok(entry.get("command", "")):
            valid.append(entry)
        else:
            errors.append(f"launcher.apps[{index}] must be a mapping with a valid command; skipped")
    if apps and not valid:
        # An explicit empty list is a parent's choice; a list of only broken entries is not.
        errors.append("launcher.apps has no usable entries; using the standard activities")
        return None
    return valid


def _valid_color(color: Any) -> bool:
    return (isinstance(color, (list, tuple)) and len(color) in (3, 4)
            and all(type(part) is int and 0 <= part <= 255 for part in color))


def _normalise(config: Dict[str, Any], errors: List[str]) -> Dict[str, Any]:
    """Replace only what would crash a reader; previously accepted values keep their meaning."""
    if not isinstance(config.get("data_root"), str) or not config["data_root"].strip():
        errors.append("data_root must be a path; using the default")
        config["data_root"] = DEFAULT_CONFIG["data_root"]
    for section in _SECTIONS:
        if section in config and not isinstance(config[section], dict):
            errors.append(f"{section} must be a mapping; using its defaults")
            config[section] = copy.deepcopy(DEFAULT_CONFIG.get(section, {}))
    for section, key in _INTEGERS:
        values = config.get(section, {})
        if key in values:
            try:
                int(values[key])
            except (TypeError, ValueError, OverflowError):
                errors.append(f"{section}.{key} must be a whole number; using the default")
                default = DEFAULT_CONFIG.get(section, {}).get(key)
                if default is None:
                    del values[key]
                else:
                    values[key] = default
    launcher = config.setdefault("launcher", {})
    apps = _valid_apps(launcher.get("apps"), errors)
    launcher["apps"] = copy.deepcopy(DEFAULT_CONFIG["launcher"]["apps"]) if apps is None else apps
    paint = config.setdefault("paint", {})
    palette = paint.get("palette")
    colors = [list(color) for color in palette if _valid_color(color)] if isinstance(palette, list) else []
    if not isinstance(palette, list) or len(colors) != len(palette):
        errors.append("paint.palette entries must be [red, green, blue] from 0 to 255; invalid colours skipped")
    paint["palette"] = colors or copy.deepcopy(DEFAULT_CONFIG["paint"]["palette"])
    return config


def _load(paths: List[Path], errors: List[str]) -> Dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    for path in paths:
        if not path.exists():
            if os.environ.get("KIDBOX_CONFIG"):
                errors.append(f"{path}: missing; using built-in defaults")
            continue
        data = _read(path, errors)
        if data is not None:
            config = _deep_merge(config, copy.deepcopy(data))
        break
    config = _normalise(config, errors)
    pinned = os.environ.get("TODDLERBOX_DATA_ROOT")
    if pinned:
        # The appliance pins child storage; a hand-edited file cannot move it.
        config["data_root"] = pinned
    launcher = config["launcher"]
    launcher["apps"] = _with_math_standard_layout(launcher["apps"])
    return config


def load_config() -> Dict[str, Any]:
    """Never raises: a damaged parent edit must not stop the child session."""
    errors: List[str] = []
    config = _load(_candidate_config_paths(), errors)
    _last_errors[:] = errors
    return config


def config_errors() -> List[str]:
    return list(_last_errors)


def check(path: Path) -> List[str]:
    errors: List[str] = []
    if not path.exists():
        return [f"{path}: missing"]
    _load([path], errors)
    return errors


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Check a ToddlerBox config file before starting child mode.")
    parser.add_argument("--check", type=Path, required=True, metavar="FILE")
    errors = check(parser.parse_args(argv).check)
    for error in errors:
        print(error)
    print("Config OK" if not errors else f"{len(errors)} problem(s); ToddlerBox will use defaults for these.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
