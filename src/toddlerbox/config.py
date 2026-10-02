from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_CONFIG: Dict[str, Any] = {
    "data_root": "/data",
    "launcher": {
        "apps": [
            {
                "name": "Paint",
                "icon_path": "assets/icons/paint.png",
                "command": "python -m toddlerbox.paint",
            },
            {
                "name": "Photos",
                "icon_path": "assets/icons/photos.png",
                "command": "python -m toddlerbox.photos",
            },
            {
                "name": "Typing",
                "icon_path": "assets/icons/typing.png",
                "command": "python -m toddlerbox.typing",
            },
            {
                "name": "Music",
                "icon_path": "assets/icons/music/music.png",
                "command": "python -m toddlerbox.music",
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
    "music": {"volume": 0.25, "autoplay": True, "latency_ms": 0},
}


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
    return config
