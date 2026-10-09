"""Bounded child-session audio startup; no writes or device selection changes."""
import math
from pathlib import Path
import subprocess
import sys
import time

from toddlerbox.config import load_config


def apply_defaults(root=Path("/")):
    """Explicit authenticated parent opt-in; ordinary updates preserve settings."""
    sys.path.insert(0, "/usr/local/lib/toddlerbox-system")
    from appliance import guard, maintenance_lock
    from boot_recovery import STATE, atomic, safe
    import yaml
    with maintenance_lock(root):
        guard(root)
        path = safe(root, Path("etc/toddlerbox/config.yaml"))
        if path.stat().st_size > 65536:
            raise ValueError("Oversized configuration")
        original = path.read_bytes()
        config = yaml.safe_load(original)
        if not isinstance(config, dict):
            raise ValueError("Configuration must be a mapping")
        for section, key, value in (("music", "volume", 1.0), ("reading", "volume", 0.70),
                                    ("math", "volume", 0.70), ("audio", "startup_volume", 0.80)):
            options = config.setdefault(section, {})
            if not isinstance(options, dict):
                raise ValueError("Audio configuration must be a mapping")
            options = config[section] = dict(options)
            options[key] = value
        backup = safe(root, STATE / "audio-config-before.yaml")
        if not backup.exists():
            atomic(backup, original)
        atomic(path, yaml.safe_dump(config, sort_keys=False).encode(), 0o644)


def startup_volume(config):
    options = config.get("audio", {})
    value = options.get("startup_volume", 0.80) if isinstance(options, dict) else 0.80
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
        value = 0.80
    return max(0.0, min(1.0, value))


def initialize(config, *, clock=time.monotonic, sleep=time.sleep, run=subprocess.run):
    """Allow the sink to appear, but never delay recovery for a missing device."""
    deadline = clock() + 1.5
    volume = startup_volume(config)
    while clock() < deadline:
        try:
            result = run(["/usr/bin/wpctl", "set-volume", "--limit", "1.0",
                          "@DEFAULT_AUDIO_SINK@", str(volume)],
                         timeout=max(0.01, min(0.4, deadline-clock())),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                run(["/usr/bin/wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
                    timeout=max(0.01, min(0.4, deadline-clock())),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                return True
        except (OSError, subprocess.SubprocessError):
            pass
        sleep(min(0.1, max(0.0, deadline-clock())))
    return False


if __name__ == "__main__":
    if sys.argv[1:] == ["--apply-defaults"]:
        apply_defaults()
    elif not sys.argv[1:]:
        try:
            initialize(load_config())
        except (OSError, ValueError):
            pass  # Audio setup cannot prevent the independently supervised session.
    else:
        raise SystemExit(2)
