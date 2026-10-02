"""Prepare/verify the Reading pack from checked-in, hash-pinned sources.

uv run python scripts/build-reading.py [--verify | --prepare-trims]
Preparation uses ffmpeg; ordinary Ubuntu image builds only copy the outputs.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import wave

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets/reading"
RATE = 44100
LETTER_PICTURES = dict(zip("abcdefghijklmnopqrstuvwxyz", [
    "apple", "bed", "cat", "dog", "egg", "fish", "goat", "hat", "ink", "jam",
    "key", "log", "map", "net", "octopus", "pig", "quilt", "rat", "sun", "top",
    "umbrella", "violin", "web", "box", "yarn", "zebra"]))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def decode(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le",
                          "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(RATE), "pipe:1"],
                         check=True, capture_output=True).stdout
    data = array.array("h")
    data.frombytes(raw)
    if sys.byteorder != "little":
        data.byteswap()
    return data


def audible_bounds(data):
    # Used for cue placement and initial edit suggestions, never during playback.
    # Keep 100ms of breathing room in stored edit bounds, including releases.
    peak = max(map(abs, data), default=0)
    if peak < 100:
        raise ValueError("Silent recording")
    threshold = max(60, peak * .015)
    indices = [i for i, value in enumerate(data) if abs(value) >= threshold]
    return indices[0], indices[-1] + 1


def pcm_bytes(data):
    copy = array.array("h", data)
    if sys.byteorder != "little":
        copy.byteswap()
    return copy.tobytes()


def save_wave(path, data):
    if not 1000 <= len(data) <= RATE * 12 or max(map(abs, data), default=0) >= 32767:
        raise ValueError("Invalid, long, or clipped render: " + str(path))
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        output.writeframes(pcm_bytes(data))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--prepare-trims", action="store_true")
    parser.add_argument("--output", type=Path, default=ASSETS)
    args = parser.parse_args()
    manifest = json.loads((ASSETS / "sources.json").read_text())
    numbers = json.loads((ASSETS / "sources/numbers-provenance.json").read_text())
    sources = manifest["sources"] + [dict(clip, path=f"sources/{clip['id']}.wav", license="MIT",
                                              credit="ToddlerBox; generated with Piper / LJ Speech")
                                     for clip in numbers["clips"]]
    for source in sources:
        if sha(ASSETS / source["path"]) != source["sha256"]:
            raise ValueError("Source hash changed: " + source["id"])
    if args.verify:
        outputs = json.loads((args.output / "outputs.json").read_text())
        for path, expected in outputs["sha256"].items():
            if sha(args.output / path) != expected:
                raise ValueError("Output hash changed: " + path)
        print(f"Verified {len(sources)} source assets and {len(outputs['sha256'])} prepared outputs")
        return

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "audio").mkdir(exist_ok=True)
    (args.output / "images").mkdir(exist_ok=True)
    pygame.init()
    pygame.display.set_mode((1, 1))
    audio, images, files, provenance = {}, {}, {}, {}
    edits_path = ASSETS / "edits.json"
    edits = json.loads(edits_path.read_text()) if edits_path.exists() else {}
    for source in sources:
        identity = source["id"]
        path = ASSETS / source["path"]
        if identity.startswith("image-"):
            filename = "images/" + identity.removeprefix("image-") + ".png"
            art = pygame.image.load_sized_svg(str(path), (512, 512))
            pygame.image.save(art, args.output / filename)
            images[identity.removeprefix("image-")] = filename
        else:
            data = decode(path)
            if args.prepare_trims:
                start, end = audible_bounds(data)
                edits[identity] = {"start": max(0, start - RATE // 10),
                                   "end": min(len(data), end + RATE // 10)}
            edit = edits[identity]
            if not 0 <= edit["start"] < edit["end"] <= len(data):
                raise ValueError("Invalid explicit edit: " + identity)
            data = data[edit["start"]:edit["end"]]
            peak = max(map(abs, data))
            rms = math.sqrt(sum(float(x) ** 2 for x in data) / len(data))
            gain = min(4.0, 3000 / max(1, rms), 25000 / max(1, peak))
            data = array.array("h", (round(x * gain) for x in data))
            filename = "audio/" + identity + ".wav"
            save_wave(args.output / filename, data)
            start, end = audible_bounds(data)
            audio[identity] = (data, {"path": filename, "frames": len(data),
                                     "cues": [{"start": start, "end": end, "unit": -1}]})
        files[filename] = sha(args.output / filename)
        provenance[filename] = {"license": source["license"], "sources": [identity]}
    if args.prepare_trims:
        json_write(edits_path, edits)

    cards = []
    by_id = {entry["id"]: entry for entry in sources}
    for word in json.loads((ASSETS / "words.json").read_text()):
        name, units = word["word"], word["units"]
        data, cues, used = array.array("h"), [], []
        for index, unit in enumerate(units):
            identity = "sound-" + {"ck": "c", "k": "c"}.get(unit, unit)
            segment, info = audio[identity]
            cue = info["cues"][0]
            cues.append({"start": len(data) + cue["start"], "end": len(data) + cue["end"], "unit": index})
            data.extend(segment)
            data.extend([0] * round(RATE * (0.15 if index < len(units) - 1 else 0.4)))
            used.append(identity)
        identity = "word-" + name
        segment, info = audio[identity]
        cue = info["cues"][0]
        cues.append({"start": len(data) + cue["start"], "end": len(data) + cue["end"], "unit": -1})
        data.extend(segment)
        used.append(identity)
        filename = "audio/sequence-" + name + ".wav"
        save_wave(args.output / filename, data)
        files[filename] = sha(args.output / filename)
        provenance[filename] = {"license": by_id[identity]["license"], "sources": used}
        cards.append({"id": "word-" + name, "kind": "words", "text": name, "units": units,
                      "sets": [word["set"]], "image": images[name],
                      "sequence": {"path": filename, "frames": len(data), "cues": cues}, "replay": info})
    for letter, picture in LETTER_PICTURES.items():
        for variant in ("sounds", "names"):
            text = "qu" if letter == "q" and variant == "sounds" else letter
            identity = "name-" + letter if variant == "names" else "sound-" + {"k": "c", "q": "qu"}.get(letter, letter)
            info = audio[identity][1]
            cards.append({"id": f"letter-{letter}-{variant}", "kind": "letters", "text": text,
                          "units": [text], "letter_audio": variant, "example": picture,
                          "image": images[picture], "sequence": info, "replay": info})
    for number in range(31):
        info = audio[f"number-{number}"][1]
        cards.append({"id": f"number-{number}", "kind": "numbers", "text": str(number),
                      "units": [str(number)], "number": number, "sequence": info, "replay": info})
    json_write(args.output / "catalog.json", {"schema_version": 1, "sample_rate": RATE, "cards": cards})
    files["catalog.json"] = sha(args.output / "catalog.json")
    json_write(args.output / "outputs.json", {"schema_version": 1, "generator": "build-reading.py v1",
                                             "sha256": dict(sorted(files.items())), "provenance": provenance})
    pygame.quit()
    print(f"Prepared {len(cards)} Reading cards: 30 words, 26 letter sounds, 26 letter names, 31 numbers")


if __name__ == "__main__":
    main()
