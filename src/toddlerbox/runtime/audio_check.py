"""Explicit, parent-only, bounded speaker check using PipeWire's installed player."""
from __future__ import annotations

import io
import math
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import wave


def tone() -> bytes:
    """One second, 440 Hz, stereo PCM16; peak 5%, with 20 ms fades."""
    rate = 44100
    frames = bytearray()
    for i in range(rate):
        envelope = min(1.0, i / 882, (rate - 1 - i) / 882)
        sample = round(32767 * .05 * envelope * math.sin(2 * math.pi * 440 * i / rate))
        frames.extend(struct.pack("<hh", sample, sample))
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(frames)
    return output.getvalue()


def main() -> int:
    if os.geteuid() == 0 or os.environ.get("TODDLERBOX_APP_CONTROL") == "1":
        print("Run this in the parent desktop terminal, without sudo.")
        return 1
    print("Start with speaker volume low. This plays one quiet, one-second tone.")
    try:
        input("Press Enter to play, or Ctrl+C to cancel: ")
        with tempfile.TemporaryDirectory(prefix="toddlerbox-audio-") as directory:
            path = Path(directory) / "tone.wav"
            path.write_bytes(tone())
            subprocess.run(["/usr/bin/pw-play", str(path)], check=True, timeout=5)
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.")
        return 0
    except (OSError, subprocess.SubprocessError):
        print("Playback failed. Check the parent desktop's sound output and PipeWire services.")
        return 1
    print("Playback completed; only listening confirms that the selected speaker worked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
