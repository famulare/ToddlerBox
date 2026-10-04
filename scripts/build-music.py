# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy==2.2.6"]
# ///
"""Build bounded sampled-piano WAVs and cues from the same canonical events.

Run with uv; normal builds are offline. --prepare-samples reads the pinned raw
downloads from build/music-research/vsco and regenerates the small instrument.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import urllib.request
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets/music"
RATE = 22050
VERSION = "toddlerbox-sampled-piano-1"
ORDER = ("mary", "twinkle", "ode", "frere", "row", "minuet",
         "buns", "bridge", "spider", "farm", "oldman", "clock", "weasel",
         "bingo", "mulberry", "lullaby", "morning", "largo")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_wave(path: Path, data: np.ndarray) -> None:
    if not np.isfinite(data).all() or np.max(np.abs(data), initial=0) >= 1:
        raise ValueError("nonfinite or clipped render")
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        output.writeframes(np.rint(data * 32767).astype("<i2").tobytes())


def prepare_samples(raw_dir: Path) -> None:
    manifest_path = ASSETS / "instrument/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for region in manifest["regions"]:
        raw = raw_dir / region["source_filename"]
        if digest(raw) != region["source_sha256"]:
            raise ValueError(f"source hash differs: {raw}")
        with wave.open(str(raw)) as source:
            if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (2, 3, 44100):
                raise ValueError("expected pinned stereo 24-bit 44100Hz source")
            packed = np.frombuffer(source.readframes(source.getnframes()), dtype=np.uint8).reshape(-1, 3)
        pcm = packed[:, 0].astype(np.int32) | (packed[:, 1].astype(np.int32) << 8) | (packed[:, 2].astype(np.int32) << 16)
        pcm = np.where(pcm >= 8388608, pcm - 16777216, pcm)
        mono = pcm.astype(np.float64).reshape(-1, 2).mean(axis=1) / 8388608
        # Trim only the source's pre-onset silence. One millisecond is retained.
        audible = np.flatnonzero(np.abs(mono) >= 0.0001)
        if not audible.size:
            raise ValueError("silent source sample")
        trim = max(0, int(audible[0]) - 44)
        mono = mono[trim:trim + 6 * 44100]
        # Fixed two-tap low-pass and decimation; no external codec tools.
        mono = mono[:len(mono) // 2 * 2].reshape(-1, 2).mean(axis=1)
        region["trim_source_frames"] = trim
        output = ASSETS / "instrument" / region["filename"]
        write_wave(output, mono)
        region["sha256"] = digest(output)
    write_json(manifest_path, manifest)


def fetch_samples(raw_dir: Path) -> None:
    """Optional maintainer-only refresh; ordinary release builds stay offline."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ASSETS / "instrument/manifest.json").read_text())
    for region in manifest["regions"]:
        target = raw_dir / region["source_filename"]
        if not target.exists():
            with urllib.request.urlopen(region["source_url"], timeout=60) as response:
                content = response.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != region["source_sha256"]:
                raise ValueError("sample download length/hash differs")
            target.write_bytes(content)
        if digest(target) != region["source_sha256"]:
            raise ValueError(f"cached sample hash differs: {target}")


def validate_score(score: dict) -> None:
    if score["schema_version"] != 1 or score["ticks_per_beat"] != 480:
        raise ValueError("unsupported score schema")
    if not 60 <= score["tempo_bpm"] <= 140:
        raise ValueError("tempo out of bounds")
    events = []
    for note in score["notes"]:
        if any(type(note[key]) is not int for key in ("pitch", "start_tick", "duration_tick", "velocity")):
            raise ValueError("note values must be integers")
        if not (48 <= note["pitch"] <= 72 and note["start_tick"] >= 0 and note["duration_tick"] > 0):
            raise ValueError("note outside keyboard or invalid duration")
        if not 1 <= note["velocity"] <= 60 or note["voice"] not in ("melody", "accompaniment"):
            raise ValueError("invalid note voice/velocity")
        events.extend(((note["start_tick"], 1), (note["start_tick"] + note["duration_tick"], -1)))
    polyphony = 0
    for _, delta in sorted(events):
        polyphony += delta
        if polyphony > 6:
            raise ValueError("polyphony exceeds six")
    end = max(t for t, _ in events) * 60 / (score["tempo_bpm"] * 480)
    if not 15 <= end <= 45 or score["intro_ms"] < 1000 or score["tail_ms"] < 1000:
        raise ValueError("arrangement length/intro/tail outside bounds")


def build(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    instrument = json.loads((ASSETS / "instrument/manifest.json").read_text())
    samples = {}
    for region in instrument["regions"]:
        path = ASSETS / "instrument" / region["filename"]
        if digest(path) != region["sha256"]:
            raise ValueError(f"instrument hash differs: {path}")
        with wave.open(str(path)) as source:
            if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, RATE):
                raise ValueError("invalid prepared instrument sample")
            samples[region["pitch_keycenter"]] = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float64) / 32767
    catalog = {"schema_version": 1, "keyboard_low": 48, "keyboard_high": 72, "tracks": []}
    renders = []
    for piece_id in ORDER:
        path = ASSETS / "scores" / (piece_id + ".json")
        score = json.loads(path.read_text())
        validate_score(score)
        ms_per_tick = 60000 / (score["tempo_bpm"] * score["ticks_per_beat"])
        cues = {"schema_version": 1, "id": piece_id, "title": score["title"], "intro_ms": score["intro_ms"], "tail_ms": score["tail_ms"], "notes": []}
        for note in sorted(score["notes"], key=lambda n: (n["start_tick"], n["pitch"], n["voice"])):
            cues["notes"].append({"pitch": note["pitch"], "start_ms": score["intro_ms"] + note["start_tick"] * ms_per_tick,
                                  "duration_ms": note["duration_tick"] * ms_per_tick, "voice": note["voice"], "velocity": note["velocity"]})
        end_ms = max(n["start_ms"] + n["duration_ms"] for n in cues["notes"])
        frame_count = math.ceil((end_ms + score["tail_ms"]) * RATE / 1000)
        cues["duration_ms"] = frame_count * 1000 / RATE
        audio = np.zeros(frame_count, dtype=np.float64)
        for note in cues["notes"]:
            region = next(r for r in instrument["regions"] if r["lokey"] <= note["pitch"] <= r["hikey"])
            source = samples[region["pitch_keycenter"]]
            ratio = 2 ** ((note["pitch"] - region["pitch_keycenter"]) / 12)
            held = round(note["duration_ms"] * RATE / 1000)
            release = round(instrument["release_ms"] * RATE / 1000)
            count = held + release
            positions = np.arange(count, dtype=np.float64) * ratio
            tone = np.interp(positions, np.arange(len(source)), source, left=0, right=0)
            attack = min(round(RATE * 0.001), held)
            tone[:attack] *= np.linspace(0, 1, attack)
            tone[held:] *= np.cos(np.linspace(0, math.pi / 2, release)) ** 2
            tone *= (note["velocity"] / 60) ** 2 * 10 ** (23 / 20)
            start = round(note["start_ms"] * RATE / 1000)
            available = min(count, len(audio) - start)
            audio[start:start + available] += tone[:available]
        renders.append((score, cues, audio, digest(path)))
    # One common gain preserves deliberate track and voice balance.
    peak = max(float(np.max(np.abs(audio))) for _, _, audio, _ in renders)
    gain = min(1, 0.65 / peak)
    provenance = {"renderer": VERSION, "renderer_sha256": digest(Path(__file__)), "numpy": np.__version__, "sample_rate": RATE, "channels": 1,
                  "sample_width": 2, "release_ms": instrument["release_ms"], "collection_gain": gain,
                  "instrument_manifest_sha256": digest(ASSETS / "instrument/manifest.json"), "tracks": []}
    for score, cues, audio, score_hash in renders:
        piece_id = score["id"]
        audio *= gain
        wav_path, cue_path = output_dir / (piece_id + ".wav"), output_dir / (piece_id + ".json")
        write_wave(wav_path, audio)
        write_json(cue_path, cues)
        catalog["tracks"].append({"id": piece_id, "title": score["title"], "audio": wav_path.name,
                                  "cues": cue_path.name, "duration_ms": cues["duration_ms"]})
        provenance["tracks"].append({"id": piece_id, "score_sha256": score_hash,
                                     "audio_sha256": digest(wav_path), "cues_sha256": digest(cue_path),
                                     "peak": float(np.max(np.abs(audio))), "rms": float(np.sqrt(np.mean(audio * audio))),
                                     "frames": len(audio), "notes": len(cues["notes"])})
        print(f"{piece_id}: {cues['duration_ms']/1000:.2f}s, {len(cues['notes'])} notes, peak {np.max(np.abs(audio)):.3f}")
    write_json(output_dir / "catalog.json", catalog)
    write_json(output_dir / "build-manifest.json", provenance)


def build_keys(output_dir: Path) -> None:
    """The same CC0 piano, 25 bounded two-second notes for independent channels."""
    output_dir.mkdir(parents=True, exist_ok=True)
    instrument = json.loads((ASSETS / "instrument/manifest.json").read_text())
    files = {}
    for pitch in range(48, 73):
        region = next(r for r in instrument["regions"] if r["lokey"] <= pitch <= r["hikey"])
        path = ASSETS / "instrument" / region["filename"]
        if digest(path) != region["sha256"]:
            raise ValueError("Instrument hash changed")
        with wave.open(str(path)) as source:
            data = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float64)/32767
        positions = np.arange(RATE*2, dtype=np.float64)*2**((pitch-region["pitch_keycenter"])/12)
        tone = np.interp(positions, np.arange(len(data)), data, left=0, right=0)
        tone[:22] *= np.linspace(0, 1, 22)
        tone[-2205:] *= np.cos(np.linspace(0, math.pi/2, 2205))**2
        tone *= min(10**(23/20), 0.5/max(0.001, np.max(np.abs(tone))))
        path = output_dir / f"{pitch}.wav"
        write_wave(path, tone)
        files[path.name] = digest(path)
    write_json(output_dir / "manifest.json", {"schema_version": 1, "license": "CC0-1.0",
               "instrument_manifest_sha256": digest(ASSETS / "instrument/manifest.json"),
               "sha256": files, "duration_seconds": 2})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ASSETS)
    parser.add_argument("--prepare-samples", type=Path, metavar="PINNED_RAW_SAMPLE_DIRECTORY")
    parser.add_argument("--fetch-samples", action="store_true", help="download pinned inputs into --prepare-samples directory; requires network")
    parser.add_argument("--keys-only", action="store_true", help="prepare the independent piano without changing song renders")
    args = parser.parse_args()
    if args.fetch_samples:
        if not args.prepare_samples:
            parser.error("--fetch-samples requires --prepare-samples DIRECTORY")
        fetch_samples(args.prepare_samples)
    if args.prepare_samples:
        prepare_samples(args.prepare_samples)
    if args.keys_only:
        build_keys(args.output)
    else:
        build(args.output)
