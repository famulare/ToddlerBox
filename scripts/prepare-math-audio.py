# /// script
# requires-python = ">=3.12"
# dependencies = ["piper-tts==1.4.2", "onnxruntime==1.30.0", "numpy==2.5.3"]
# ///
"""Optional maintainer preparation. The shipped app plays checked-in WAVs.

uv run scripts/prepare-math-audio.py --model-dir PATH
Download the pinned voice separately; this script never accesses the network.
"""
import argparse
from contextlib import chdir
import hashlib
import json
from pathlib import Path
import wave
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
REVISION = "c10ece1aade47bb51c153c893d14e5bf8e5b7117"
MODEL = "en_US-ljspeech-medium.onnx"
HASHES = {
    MODEL: "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22",
    MODEL + ".json": "141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860",
}
NAMES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
for tens in ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"):
    if tens != "twenty":
        NAMES.append(tens)
    NAMES.extend(tens + " " + NAMES[i] for i in range(1, 10))
NAMES.append("one hundred")


def prepare(args):
    # Some inference builds create diagnostic files at import time. Confine
    # them to the temporary preparation directory, never the repository.
    import onnxruntime
    from piper import PiperVoice, SynthesisConfig
    for name, expected in HASHES.items():
        if hashlib.sha256((args.model_dir / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Unexpected model: " + name)
    onnxruntime.disable_telemetry_events()
    onnxruntime.set_seed(0)
    voice = PiperVoice.load(args.model_dir / MODEL, use_cuda=False)
    settings = SynthesisConfig(noise_scale=0, noise_w_scale=0, length_scale=1.05,
                               normalize_audio=True, volume=0.7)
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    operators = []
    texts = ([] if args.operators_only else [(f"number-{n}", name, n) for n, name in enumerate(NAMES)])
    texts += [(name, name, None) for name in ("plus", "minus", "equals")]
    for identifier, name, number in texts:
        path = args.output / f"{identifier}.wav"
        with wave.open(str(path), "wb") as target:
            voice.synthesize_wav(name.capitalize() + ".", target, syn_config=settings)
        raw = path.with_suffix(".raw.wav")
        path.rename(raw)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-ar", "44100",
                        "-ac", "1", "-c:a", "pcm_s16le", str(path)], check=True)
        raw.unlink()
        with wave.open(str(path), "rb") as clip:
            frames = clip.getnframes()
        row = {"id": identifier, "text": name, "frames": frames,
               "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        if number is None:
            operators.append(row)
        else:
            records.append({**row, "number": number})
    metadata = {"schema_version": 1, "sample_rate": 44100, "generator": "Piper 1.4.2, CPU; zero inference noise",
                "model_revision": REVISION, "model_hashes": HASHES,
                "model_url": f"https://huggingface.co/rhasspy/piper-voices/tree/{REVISION}/en/en_US/ljspeech/medium",
                "model_license": "MIT (repository metadata)",
                "dataset": "LJ Speech, public domain",
                "speaker": "LJ Speech single US English female voice",
                "generated_audio_license": "MIT; ToddlerBox project license",
                "settings": {"noise_scale": 0, "noise_w_scale": 0, "length_scale": 1.05, "volume": 0.7},
                "clips": records, "operators": operators}
    if args.operators_only:
        previous = json.loads((args.output / "catalog.json").read_text())
        assert previous["model_hashes"] == HASHES and previous["settings"] == metadata["settings"]
        previous["operators"] = operators
        metadata = previous
    (args.output / "catalog.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Prepared {len(records)} complete number names and {len(operators)} equation words")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "assets/math/audio")
    parser.add_argument("--operators-only", action="store_true", help="Preserve existing number clips and add equation words")
    args = parser.parse_args()
    args.model_dir, args.output = args.model_dir.resolve(), args.output.resolve()
    with TemporaryDirectory(prefix="toddlerbox-math-") as scratch, chdir(scratch):
        prepare(args)


if __name__ == "__main__":
    main()
