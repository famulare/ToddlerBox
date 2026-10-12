"""Record actual old/new SDL held piano and song overlap, using public assets.

uv run --frozen python scripts/check-music-sustain.py --baseline BASELINE --output OUTPUT
Requires a real baseline checkout/archive. No reconstructed piano, private data,
speaker calibration or real hardware claims. SDL's disk driver captures PCM.
"""
from array import array
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import Mock


def capture(source, output, kind):
    sys.path.insert(0, str(source.resolve() / "src"))
    os.environ.update(SDL_AUDIODRIVER="disk", SDL_DISKAUDIOFILE=str(output.resolve()),
                      SDL_DISKAUDIODELAY="11", PYGAME_HIDE_SUPPORT_PROMPT="1")
    import pygame
    from toddlerbox.music.piano import Piano
    from toddlerbox.music.library import load_library
    from toddlerbox.music.playback import MusicPlayer
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    piano = Piano({}, Mock())
    song = None
    if kind == "overlap":
        tracks, _, _ = load_library(source.resolve() / "assets/music", Mock())
        song = MusicPlayer(tracks, Mock())
        song.select(0)
    for token in range(8 if song else 1):
        piano._play(token, 60)
    maximum = 0
    deadline = time.monotonic() + 3.2
    while time.monotonic() < deadline:
        piano.update()
        maximum = max(maximum, sum(channel.get_volume() for channel in piano.channels.values()
                                  if channel.get_busy()))
        if song:
            song.update()
            assert pygame.mixer.music.get_busy()
        time.sleep(1/60)
    release_frame = output.stat().st_size // 4
    held_busy = sum(channel.get_busy() for channel in piano.channels.values())
    for token in list(piano.voices):
        piano._release(token)
    deadline = time.monotonic() + .75
    while time.monotonic() < deadline:
        piano.update()
        time.sleep(1/60)
    channels = list(piano.channels.values())
    piano.close()
    assert not any(channel.get_busy() for channel in channels)
    if song:
        song.close()
    time.sleep(.12)
    pygame.mixer.quit()
    samples = array("h", output.read_bytes())
    late = samples[max(0, (release_frame-22050)*2):release_frame*2]
    active = [i//2 for i, value in enumerate(samples) if value]
    report = {"held_busy": held_busy, "late_hold_rms": math.sqrt(sum(v*v for v in late)/len(late))/32768,
              "peak": max(abs(v) for v in samples),
              "saturated_samples": sum(abs(v)>=32767 for v in samples),
              "max_key_gain": maximum, "post_close_silent": not any(samples[-4410:]),
              "tail_ms": (max(active)-release_frame)*1000/44100 if not song else None}
    output.with_suffix(".json").write_text(json.dumps(report, indent=2)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--kind", choices=("solo", "overlap"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.capture:
        capture(args.capture, args.output, args.kind)
        return
    if not args.baseline:
        parser.error("--baseline or --capture is required")
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    reports = {}
    for label, source in (("baseline", args.baseline.resolve()), ("candidate", root)):
        reports[label] = {}
        for kind in ("solo", "overlap"):
            output = (args.output / f"{label}-{kind}.raw").resolve()
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--capture", str(source),
                            "--kind", kind, "--output", str(output)], check=True)
            reports[label][kind] = json.loads(output.with_suffix(".json").read_text())
    assert reports["baseline"]["solo"]["held_busy"] == 0
    assert reports["baseline"]["solo"]["late_hold_rms"] == 0
    assert reports["candidate"]["solo"]["held_busy"] == 1
    assert reports["candidate"]["solo"]["late_hold_rms"] > .05
    assert 450 < reports["candidate"]["solo"]["tail_ms"] < 800
    assert reports["candidate"]["overlap"]["held_busy"] == 8
    assert all(row["max_key_gain"] <= .70 and row["saturated_samples"] == 0
               and row["post_close_silent"] for row in reports["candidate"].values())
    # Preserve existing recordings; only new attack/loop derivatives are added.
    unchanged = 0
    changed_songs = 0
    import hashlib
    for folder in ("reading", "math", "music"):
        for path in (args.baseline / "assets" / folder).rglob("*"):
            if path.is_file():
                current = root / path.relative_to(args.baseline)
                if path.suffix in {".wav", ".png"}:
                    if folder == "music" and path.parent == args.baseline / "assets/music" and path.suffix == ".wav":
                        assert path.read_bytes() != current.read_bytes()
                        changed_songs += 1
                        continue
                    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(current.read_bytes()).digest()
                    unchanged += 1
    reports["unchanged_existing_media"] = unchanged
    assert changed_songs == 18
    reports["intentionally_louder_songs"] = changed_songs
    (args.output / "results.json").write_text(json.dumps(reports, indent=2)+"\n")
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
