# /// script
# requires-python = ">=3.12"
# dependencies = ["piper-tts==1.4.2", "onnxruntime==1.30.0", "numpy==2.5.3"]
# ///
"""Optional maintainer preparation. The shipped app plays checked-in WAVs.

uv run scripts/prepare-reading-numbers.py --model-dir PATH
Download the pinned voice separately; this script never accesses the network.
"""
import argparse
from contextlib import chdir
import hashlib
import json
from pathlib import Path
import wave
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
REVISION = "c10ece1aade47bb51c153c893d14e5bf8e5b7117"
MODEL = "en_US-ljspeech-medium.onnx"
HASHES = {
    MODEL: "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22",
    MODEL + ".json": "141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860",
}
NAMES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
NAMES += ["twenty " + NAMES[i] for i in range(1, 10)] + ["thirty"]


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
    for number, name in enumerate(NAMES):
        path = args.output / f"number-{number}.wav"
        with wave.open(str(path), "wb") as target:
            voice.synthesize_wav(name.capitalize() + ".", target, syn_config=settings)
        records.append({"id": f"number-{number}", "text": name,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    metadata = {"schema_version": 1, "generator": "Piper 1.4.2, CPU; zero inference noise",
                "model_revision": REVISION, "model_hashes": HASHES,
                "model_url": f"https://huggingface.co/rhasspy/piper-voices/tree/{REVISION}/en/en_US/ljspeech/medium",
                "model_license": "MIT (repository metadata)",
                "dataset": "LJ Speech, public domain",
                "speaker": "LJ Speech single US English female voice",
                "generated_audio_license": "MIT; ToddlerBox project license",
                "settings": {"noise_scale": 0, "noise_w_scale": 0, "length_scale": 1.05, "volume": 0.7},
                "clips": records}
    (args.output / "numbers-provenance.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Prepared {len(records)} complete number names")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "assets/reading/sources")
    args = parser.parse_args()
    args.model_dir, args.output = args.model_dir.resolve(), args.output.resolve()
    with TemporaryDirectory(prefix="toddlerbox-reading-") as scratch, chdir(scratch):
        prepare(args)


if __name__ == "__main__":
    main()
