#!/usr/bin/env python3
"""Compare real old/new SDL mixer output. Use an actual git archive as baseline.

uv run --frozen python scripts/check-audio-polish.py --baseline BASELINE --output OUTPUT
No physical speaker or private data is required; SDL's disk driver captures PCM.
"""
import argparse
from array import array
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import Mock
import wave


def capture(source, output, kind):
    sys.path.insert(0, str(source / "src"))
    os.chdir(source)
    os.environ.update(SDL_AUDIODRIVER="disk", SDL_DISKAUDIOFILE=str(output),
                      SDL_DISKAUDIODELAY="11", PYGAME_HIDE_SUPPORT_PROMPT="1")
    import pygame
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    signal = output.with_suffix(".wav")
    with wave.open(str(signal), "wb") as stream:
        stream.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
        stream.writeframes(array("h", [20000, -20000] * 22050).tobytes())
    if kind == "song":
        from toddlerbox.music.library import Track
        from toddlerbox.music.playback import MusicPlayer
        player = MusicPlayer([Track("test", "Test", signal, 1000, ())], Mock())
        player.select(0)
    elif kind in {"reading", "math"}:
        from toddlerbox.reading.catalog import Speech
        from toddlerbox.reading.playback import SDLSpeech
        if kind == "reading":
            from toddlerbox.reading.playback import SpeechPlayer
            gain = SpeechPlayer(Mock()).volume
        else:
            from toddlerbox.math.model import Options
            gain = Options().volume
        player = SDLSpeech()
        player.play(Speech(signal, 44100, ()), gain)
    else:
        from toddlerbox.music.piano import Piano
        player = Piano({}, Mock())
        player._play("key", 60)
        if kind == "overlap":
            from toddlerbox.music.library import Track
            from toddlerbox.music.playback import MusicPlayer
            song = MusicPlayer([Track("test", "Test", signal, 1000, ())], Mock())
            song.select(0)
    time.sleep(.12)
    release_frame = output.stat().st_size // 4
    max_key_gain = 0.0
    if kind in {"piano", "overlap"}:
        player._release("key")
        until = time.monotonic() + .75
        strikes = 0
        while time.monotonic() < until:
            if kind == "overlap" and strikes < 16:
                player._play(strikes, 48 + strikes % 25)
                player._release(strikes)
                strikes += 1
            if hasattr(player, "update"):
                player.update()
            max_key_gain = max(max_key_gain, sum(voice.get_volume() for voice in player.channels.values()
                                                if voice.get_busy()))
            time.sleep(1/60)
        player.close()
        if kind == "overlap":
            song.close()
    else:
        time.sleep(.2)
        if kind == "song":
            player.close()
        else:
            player.stop()
    close_frame = output.stat().st_size // 4
    time.sleep(.1)
    pygame.mixer.quit()
    samples = array("h", output.read_bytes())
    active = [i // 2 for i, value in enumerate(samples) if value]
    report = {"peak": max(abs(v) for v in samples), "release_frame": release_frame,
              "close_frame": close_frame, "last_nonzero_frame": max(active),
              "tail_ms": (max(active)-release_frame)*1000/44100,
              "saturated_samples": sum(abs(v) >= 32767 for v in samples),
              "max_key_gain": max_key_gain}
    output.with_suffix(".json").write_text(json.dumps(report, indent=2)+"\n")


def compare(baseline, output):
    output.mkdir(parents=True, exist_ok=True)
    sources = {"baseline": baseline, "candidate": Path(__file__).resolve().parents[1]}
    reports = {}
    for name, source in sources.items():
        reports[name] = {}
        for kind in ("song", "reading", "math", "piano", "overlap"):
            raw = output / f"{name}-{kind}.raw"
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--capture",
                            str(source), "--output", str(raw), "--kind", kind], check=True)
            reports[name][kind] = json.loads(raw.with_suffix(".json").read_text())
    for kind, low, high in (("song",3.99,4.01),("reading",1.99,2.05),("math",1.99,2.05)):
        ratio = reports["candidate"][kind]["peak"] / reports["baseline"][kind]["peak"]
        assert low <= ratio <= high, (kind, ratio)
        reports["candidate"][kind]["gain_ratio"] = ratio
    assert reports["baseline"]["piano"]["tail_ms"] < 180
    assert 450 < reports["candidate"]["piano"]["tail_ms"] < 740
    assert reports["candidate"]["overlap"]["max_key_gain"] <= .70
    assert all(row["saturated_samples"] == 0 for row in reports["candidate"].values())
    (output / "results.json").write_text(json.dumps(reports, indent=2)+"\n")
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kind", choices=("song", "reading", "math", "piano", "overlap"))
    args = parser.parse_args()
    if args.capture:
        capture(args.capture.resolve(), args.output.resolve(), args.kind)
    elif args.baseline:
        compare(args.baseline.resolve(), args.output.resolve())
    else:
        parser.error("--baseline is required")
