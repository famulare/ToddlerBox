# Math number speech

`audio/` contains 101 offline recordings of complete English number names,
zero through one hundred. These are synthetic speech, not family recordings.
Three additional recordings say "plus", "minus" and "equals" using the same
pinned voice. Arithmetic speech plays the two operands, operation, equals and
answer in order. All five clips are checked before starting; early stops and
device failures cancel the rest instead of skipping words.
The application uses the existing SDL mixer and never runs a speech model.

Preparation uses Piper 1.4.2 with the single US English female LJ Speech voice,
CPU inference, zero synthesis noise, length scale 1.05 and synthesis volume 0.7.
FFmpeg resamples to 44,100 Hz, mono, signed 16-bit PCM. `audio/catalog.json`
records the exact clip SHA-256 hashes, sample counts, synthesis settings, model
revision and hashes. All files are validated before first playback, within a
six-second/600KB per-file budget; the cache contains metadata, not PCM buffers.

Source and license references:

- [Pinned Piper voice source](https://huggingface.co/rhasspy/piper-voices/tree/c10ece1aade47bb51c153c893d14e5bf8e5b7117/en/en_US/ljspeech/medium).
  The voice repository metadata declares MIT.
- [LJ Speech dataset](https://keithito.com/LJ-Speech-Dataset/), public-domain
  recordings of public-domain books. One speaker; no new personal voice input.
- [Piper 1.4.2](https://github.com/OHF-Voice/piper1-gpl), GPL-3.0, used only as a
  maintainer preparation tool, not shipped in the application runtime.
- Generated WAVs and preparation code are distributed under ToddlerBox's MIT
  [license](../../LICENSE). No model weights are shipped.

Reproduce using the hash-checked public model downloaded separately:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run --frozen --script scripts/prepare-math-audio.py \
  --model-dir build/reading-research/piper
```

The accompanying script lock pins preparation dependencies. The initial build
used FFmpeg 7.1.5 and records raw output hashes; regeneration across different
inference/FFmpeg platforms may differ, so changes require validation. Automated
checks verify every file's exact hash, format, complete payload, duration and
unclipped audible PCM. Parent listening still checks pronunciation, comfort and
actual device routing. Speaker playback never controls visual revelation.

Math illustrations reuse Reading's unchanged artwork and
[provenance](../reading/README.md). The launcher icon provenance is documented
in the main README; this sound follow-up leaves it unchanged.
