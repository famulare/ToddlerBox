from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

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
    paths = []
    if env_path:
        paths.append(Path(env_path))
    paths.extend([
        Path("config.yaml"),
        Path("/opt/toddlerbox/config.yaml"),
    ])
    return paths


def load_config() -> Dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    for path in _candidate_config_paths():
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            if isinstance(data, dict):
                config = _deep_merge(config, data)
            break
    launcher = config.get("launcher")
    if isinstance(launcher, dict):
        apps = launcher.get("apps")
        augmented = _with_math_standard_layout(apps)
        if augmented is not apps:
            config = {**config, "launcher": {**launcher, "apps": augmented}}
    return config
