"""Compare genuine old/new outputs under identical inputs; use a baseline archive.

uv run python scripts/check-child-paced-baseline.py --baseline /path/to/890f793
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/reading-piano-qa/comparison"))
    parser.add_argument("--all-activities", action="store_true", help="Compare Music and Reading too when their behavior is unchanged")
    parser.add_argument("--exclude-launcher", action="store_true", help="Explicitly omit intentional launcher changes; keep all activity/save comparisons")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    old, output = args.baseline.resolve(), args.output.resolve()
    counts = {"unchanged_frames": 0, "unchanged_saved_outputs": 0, "unchanged_media": 0}
    for name, source in (("old", old), ("new", root)):
        subprocess.run([sys.executable, str(root/"scripts/check-sync-rendering.py"),
                        "--render", str(source), "--output", str(output/name),
                        "--state", "baseline"], check=True)
    frames = {"launcher", "paint", "photos", "typing"}
    if args.all_activities:
        frames.update({"music", "reading"})
    if args.exclude_launcher:
        frames.discard("launcher")
    for size in ("1024x600", "1366x768"):
        for original in (output/"old"/size).iterdir():
            if original.stem in frames or original.name.startswith("saved-"):
                assert original.read_bytes() == (output/"new"/size/original.name).read_bytes(), original
                key = "unchanged_saved_outputs" if original.name.startswith("saved-") else "unchanged_frames"
                counts[key] += 1
    for directory in ("assets/music", "assets/reading/audio", "assets/reading/images", "assets/reading/sources"):
        for original in (old/directory).rglob("*"):
            if not original.is_file() or original.suffix not in {".wav", ".ogg", ".png", ".svg", ".json"}:
                continue
            if original.name.startswith("number-") or original.name == "numbers-provenance.json":
                continue  # Intentionally removed, with number cards/configuration.
            candidate = root/original.relative_to(old)
            assert hashlib.sha256(original.read_bytes()).digest() == hashlib.sha256(candidate.read_bytes()).digest(), original
            counts["unchanged_media"] += 1
    (output/"result.json").write_text(json.dumps(counts, indent=2)+"\n")
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
