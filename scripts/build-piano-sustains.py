# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy==2.2.6"]
# ///
"""Prepare bounded attack/loop PCM from the existing verified CC0 piano.

uv run --locked scripts/build-piano-sustains.py --output DIRECTORY
No downloads, song changes, runtime synthesis or runtime NumPy dependency.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("music_builder", ROOT / "scripts/build-music.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
RATE = builder.RATE


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    instrument = json.loads((builder.ASSETS / "instrument/manifest.json").read_text())
    records = {}
    for pitch in range(48, 73):
        region = next(r for r in instrument["regions"] if r["lokey"] <= pitch <= r["hikey"])
        path = builder.ASSETS / "instrument" / region["filename"]
        if builder.digest(path) != region["sha256"]:
            raise ValueError("Instrument hash changed")
        with wave.open(str(path)) as source:
            data = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float64)/32767
        positions = np.arange(RATE, dtype=np.float64)*2**((pitch-region["pitch_keycenter"])/12)
        tone = np.interp(positions, np.arange(len(data)), data, left=0, right=0)
        frequency = 440 * 2**((pitch-69)/12)
        period = RATE / frequency
        anchor = round(.12*RATE)
        crossings = np.flatnonzero((tone[:-1] <= 0) & (tone[1:] > 0)) + 1
        nearby = crossings[np.abs(crossings-anchor) <= round(period)]
        if not len(nearby):
            raise ValueError("No safe loop anchor")
        start = int(nearby[np.argmin(np.abs(nearby-anchor))])
        target_end = start + round(64*period)
        endings = crossings[np.abs(crossings-target_end) <= round(period)]
        if not len(endings):
            raise ValueError("No safe loop endpoint")
        end = int(endings[np.argmin(np.abs(endings-target_end))])
        length, blend = end - start, round(4*period)
        loop = tone[start:start+length].copy()
        # Blend the continuation into the head at the wrap. The overlap spans
        # whole nominal periods; this avoids looping the percussive attack.
        weights = np.linspace(0, 1, blend)
        loop[:blend] = tone[start+length:start+length+blend]*(1-weights) + loop[:blend]*weights
        rms = float(np.sqrt(np.mean(loop*loop)))
        peak = float(np.max(np.abs(loop)))
        loop *= min(.14/max(rms, .00001), .50/max(peak, .00001))
        attack = tone[:start].copy()
        attack *= min(10**(23/20), .50/max(float(np.max(np.abs(attack))), .00001))
        attack[:22] *= np.linspace(0, 1, 22)
        crossfade = min(blend, len(attack))
        weights = np.linspace(0, 1, crossfade)
        attack[-crossfade:] = attack[-crossfade:]*(1-weights) + loop[-crossfade:]*weights
        for kind, pcm in (("attack", attack), ("loop", loop)):
            target = output / f"{pitch}-{kind}.wav"
            builder.write_wave(target, pcm)
            records[target.name] = {"sha256": builder.digest(target), "frames": len(pcm),
                                    "peak": float(np.max(np.abs(pcm))),
                                    "rms": float(np.sqrt(np.mean(pcm*pcm)))}
    builder.write_json(output / "manifest.json", {
        "schema_version": 1, "license": "CC0-1.0", "renderer": "piano-sustain-1",
        "renderer_sha256": builder.digest(Path(__file__)), "numpy": np.__version__,
        "instrument_manifest_sha256": builder.digest(builder.ASSETS / "instrument/manifest.json"),
        "sample_rate": RATE, "channels": 1, "sample_width": 2,
        "loop_cycles": 64, "crossfade_cycles": 4, "target_loop_rms": .14,
        "peak_ceiling": .50, "files": records})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=builder.ASSETS / "keys/sustain")
    build(parser.parse_args().output)
