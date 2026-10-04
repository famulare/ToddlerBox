"""Disposable fresh-install VM check, starting at the 1280x800 child launcher.

uv run --frozen python scripts/qualify-child-paced-vm.py
Use system/vm.sh; override TODDLERBOX_VM_DIR for a differently mounted VM.
Exercises real QMP input, frame pixels and emulated HDA output, without credentials.
"""
import json
import os
from pathlib import Path
import struct
import sys
import time
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "system"))
from qmp import command

ROOT = Path(os.environ.get("TODDLERBOX_VM_DIR", "build/vm"))


def click(x, y):
    command("input-send-event", {"events": [
        {"type": "abs", "data": {"axis": "x", "value": int(x * 32767 / 1279)}},
        {"type": "abs", "data": {"axis": "y", "value": int(y * 32767 / 799)}}]})
    time.sleep(.5)
    for down in (True, False):
        command("input-send-event", {"events": [{"type": "btn", "data": {"down": down, "button": "left"}}]})
        time.sleep(.15)


def screenshot(name):
    command("screendump", {"filename": f"/build/vm/{name}.ppm"})
    Image.open(ROOT / f"{name}.ppm").save(ROOT / f"{name}.png")


def offset():
    return (ROOT / "audio.wav").stat().st_size


def capture(start):
    with (ROOT / "audio.wav").open("rb") as stream:
        stream.seek(start)
        data = stream.read()
    values = struct.unpack("<" + "h" * (len(data) // 2), data[:len(data) // 2 * 2])
    return {"bytes": len(data), "peak": max(map(abs, values), default=0)}


def main():
    results = {}
    click(1120, 400)
    time.sleep(3)
    click(140, 194)
    time.sleep(1)
    screenshot("reading-before")
    start = offset()
    click(635, 206)
    time.sleep(2)
    screenshot("reading-after-sound")
    results["reading_sound"] = capture(start)
    assert results["reading_sound"]["peak"] > 0
    crop = (300, 360, 1100, 745)
    before = Image.open(ROOT / "reading-before.png").crop(crop)
    after = Image.open(ROOT / "reading-after-sound.png").crop(crop)
    assert ImageChops.difference(before, after).getbbox() is None
    start = offset()
    click(708, 324)
    time.sleep(2)
    screenshot("reading-after-word")
    results["reading_word"] = capture(start)
    assert results["reading_word"]["peak"] > 0
    assert ImageChops.difference(before, Image.open(ROOT / "reading-after-word.png").crop(crop)).getbbox()
    click(195, 125)
    screenshot("reading-picture-selector")
    click(1235, 45)
    time.sleep(1)
    start = offset()
    time.sleep(1)
    results["reading_home"] = capture(start)
    assert results["reading_home"]["peak"] == 0
    click(880, 400)
    time.sleep(2)
    screenshot("music-song")
    start = offset()
    time.sleep(1)
    results["music_song"] = capture(start)
    assert results["music_song"]["peak"] > 0
    click(710, 725)
    screenshot("music-play-along")
    click(120, 519)
    time.sleep(1)
    screenshot("music-free-play")
    start = offset()
    time.sleep(1)
    results["free_play_idle"] = capture(start)
    assert results["free_play_idle"]["peak"] == 0
    start = offset()
    click(710, 725)
    time.sleep(.7)
    results["free_play_note"] = capture(start)
    assert results["free_play_note"]["peak"] > 0
    click(1235, 45)
    time.sleep(1)
    start = offset()
    time.sleep(1)
    results["music_home"] = capture(start)
    assert results["music_home"]["peak"] == 0
    (ROOT / "playback-results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(results)


if __name__ == "__main__":
    main()
