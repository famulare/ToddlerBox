"""Prepare isolated listening previews; never changes the Reading pack.

Usage: python docs/dev/issue-25-preview.py /absolute/ignored/preview-directory
Download candidate-plum.ogg there first, using the URL in issue-25.md.
"""
from __future__ import annotations

import array
import hashlib
import os
from pathlib import Path
import runpy
import shutil
import sys
import wave

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "assets/reading"
EXPECTED = "ecc24b1e912a7079877e51fa9af6d1ebc5d3d755098a0c2a2cf526151cb332ec"


def main():
    output = Path(sys.argv[1]).resolve()
    if output == PACK or PACK in output.parents:
        raise ValueError("Preview directory must be outside the product pack")
    candidate = output / "candidate-plum.ogg"
    assert hashlib.sha256(candidate.read_bytes()).hexdigest() == EXPECTED
    helpers = runpy.run_path(str(ROOT / "scripts/build-reading.py"))
    pygame.mixer.init(frequency=44100, size=-16, channels=1)
    try:
        raw = pygame.mixer.Sound(str(candidate)).get_raw()
    finally:
        pygame.mixer.quit()
    data = array.array("h")
    data.frombytes(raw)
    # SDL_mixer returns native-endian PCM. Retain the full source, with no trim.
    rms = (sum(float(value) ** 2 for value in data) / len(data)) ** 0.5
    gain = min(4.0, 3000 / max(1, rms), 25000 / max(1, max(map(abs, data))))
    data = array.array("h", (round(value * gain) for value in data))
    helpers["save_wave"](output / "candidate-word-plum.wav", data)
    with wave.open(str(PACK / "audio/sequence-plum.wav")) as recording:
        baseline = recording.readframes(recording.getnframes())
    with wave.open(str(PACK / "audio/word-plum.wav")) as recording:
        replay = recording.readframes(recording.getnframes())
    assert baseline.endswith(replay)
    prefix = array.array("h")
    prefix.frombytes(baseline[:-len(replay)])
    if sys.byteorder != "little":
        prefix.byteswap()
    offset = len(prefix)
    prefix.extend(data)
    helpers["save_wave"](output / "candidate-sequence-plum.wav", prefix)
    for name in ("word-plum.wav", "sequence-plum.wav", "word-drum.wav", "sound-u.wav"):
        shutil.copyfile(PACK / "audio" / name, output / ("baseline-" + name))
    shutil.copyfile(PACK / "sources/word-plum.ogg", output / "baseline-source-plum.ogg")
    start, end = helpers["audible_bounds"](data)
    helpers["json_write"](output / "preview.json", {
        "status": "unapproved listening candidate; not installed",
        "author": "Dvortygirl, 2006",
        "source_url": "https://upload.wikimedia.org/wikipedia/commons/a/a3/En-us-plum.ogg",
        "description_revision": "https://commons.wikimedia.org/w/index.php?title=File:En-us-plum.ogg&oldid=1229152823",
        "license": "CC-BY-SA-3.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
        "changes": "SDL_mixer decode to mono 44100Hz signed 16-bit; bounded gain; no trim; sequence uses unchanged baseline phonemes and gaps",
        "pygame": pygame.version.ver,
        "sdl_mixer": list(pygame.mixer.get_sdl_mixer_version()),
        "candidate_frames": len(data),
        "gain": gain,
        "replay_cue": {"start": start, "end": end, "unit": -1},
        "sequence_final_cue": {"start": offset + start, "end": offset + end, "unit": -1},
        "sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in sorted(output.iterdir()) if path.suffix in {".wav", ".ogg"}},
    })


if __name__ == "__main__":
    main()
