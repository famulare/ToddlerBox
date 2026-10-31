# Issue #25: plum pronunciation investigation and listening candidate

2026-10-31. Status: **parent approved the candidate and different speaker;
correction integrated into development assets, not installed or released**.
The parent heard the local preview and replied “new one is correct. thanks!”
after being asked to approve both pronunciation and the different speaker.
This records the parent’s listening result, not agent or automated hearing. Baseline worktree source:
`411f71294797b83569b63385bc072b870a114258` (the agreed 0.5.3 issue plan).
Reading media match public main `b3d87f95bd160cf5de538f122e6b9537fd82370a`.
Design contract: Reading's deliberate offline word/sound playback and licensed
prepared content. No runtime/UI/artwork/spelling behavior changes are proposed.

## Historical baseline before correction

The checked-in original is Smart4Kids/Art4Apps (2011), CC-BY-SA-3.0,
distributed by GCompris at immutable revision
`5cfd4e4a4236701ec5e9d04a1796b6837d945403`, path
`voices/en_US/words/plum.ogg`. Its Vorbis comment identifies
`copyright=CC BY-SA`, `artist=Smart4Kids.com`, `date=2011`; the upstream credit
is preserved in `assets/reading/licenses/GCompris-expansion-credits.txt`.

| File | SHA-256 |
| --- | --- |
| `sources/word-plum.ogg` | `91c8fdf53d827fceb5e6fa215e0ab8920fe59395e95ae3421653bbf8454cf4a9` |
| `audio/word-plum.wav` | `e9d61d461031f6e498ee1d0de874b012d15cabf465722edfbaf68088cf1e2c38` |
| `audio/sequence-plum.wav` | `a8e568788e73eabaeac0573305fdbf66cfc6aba0338a0d39e526882c15709cca` |
| `audio/sound-u.wav` | `30c2508b772dc64f9ae794b213a4d197382cb63f3878b1cb0ffee114b957ab22` |

`edits.json` selects decoded frames `[185, 36864)` for the word, yielding
36,679 mono 44.1kHz frames (0.832s). The leading trim is 4.2ms. Replay's audible
cue is `[4410, 32737)`. The full sequence has 335,468 frames, with the complete
replay starting at frame 298,789 and its final cue `[303199, 331526)`.

The new focused test proves the sequence contains the exact checked-in `p`, `l`,
`u`, `m` PCM clips, exact silent gaps and complete whole-word replay, with matching
cue offsets. No assembly substitution, sample-rate mismatch or missing replay
fragment was found. The isolated `u` is a shared Buzzphonics MIT clip, also used
by other words; changing it globally would affect unrelated teaching content.
These structural checks do not establish what vowel a human hears in the source,
trimmed word or sound unit. No source-listening diagnosis is claimed.

## Isolated licensed candidate

An alternative is [Dvortygirl's US English recording, 28 October
2006](https://commons.wikimedia.org/w/index.php?title=File:En-us-plum.ogg&oldid=1229152823).
The source page permits selecting CC-BY-SA-3.0 from its multiple licenses.
Original download:
<https://upload.wikimedia.org/wikipedia/commons/a/a3/En-us-plum.ogg>.
Downloaded bytes: 10,086; SHA-256
`ecc24b1e912a7079877e51fa9af6d1ebc5d3d755098a0c2a2cf526151cb332ec`.
SHA-1 `47a11ce69c7e860b1e6ed20fd2fdd2f1118ee4eb` also matches the Commons page.
Attribution: Dvortygirl, 2006, Wikimedia Commons;
[CC-BY-SA-3.0](https://creativecommons.org/licenses/by-sa/3.0/).
Preview transformations: mono 44.1kHz signed 16-bit decode, bounded gain using
the pack's normalization policy, no trim; sequence retains the baseline's exact
phonemes and gaps. The speaker differs from the current word's speaker.

Local previews are isolated under the ignored directory
`/home/parent/toddlerbox/build/issue-25-preview/`. The original listening set contains
baseline source/replay/sequence, `baseline-word-drum.wav`, `baseline-sound-u.wav`,
the candidate source, `candidate-word-plum.wav`, `candidate-sequence-plum.wav`,
`preview.json` and a copy of the CC-BY-SA-3.0 license.

Candidate replay: 25,600 frames, cue `[3329, 22633)`, SHA-256
`97f83486c05bc272bef820d82a803c8b448faf5f598010535dacd0a240fa0c0e`.
Candidate sequence: 324,389 frames, final cue `[302118, 321422)`, SHA-256
`561d509e283461b57665d4270fb882fe3b295421c40d205afadf6f516cc01c38`.
These approved preview values now match the product catalogue and output hashes.

Reproduction from the issue worktree (no new packages or global tools installed):

```sh
mkdir -p /home/parent/toddlerbox/build/issue-25-preview
curl --fail --location --max-time 45 https://upload.wikimedia.org/wikipedia/commons/a/a3/En-us-plum.ogg --output /home/parent/toddlerbox/build/issue-25-preview/candidate-plum.ogg
UV_CACHE_DIR=/tmp/tbx-release-uv-cache uv run --offline --no-project --python /tmp/toddlerbox-053/.venv/bin/python python docs/dev/issue-25-preview.py /home/parent/toddlerbox/build/issue-25-preview
cp assets/reading/licenses/CC-BY-SA-3.0.txt /home/parent/toddlerbox/build/issue-25-preview/LICENSE-CC-BY-SA-3.0.txt
```

Preview decoder/toolchain: Python 3.12.3, pygame-ce 2.5.8, SDL 2.32.10,
SDL_mixer 2.8.2. The script checks the source hash before decoding and records
versions, gain, cues and all audio hashes in `preview.json`. It never plays audio.
The ordinary preparation script requires ffmpeg, which is absent on this host;
the SDL preview is not represented as an ffmpeg byte-reproducible product build.

## Historical listening guidance and alternatives

The parent has completed this gate and selected the Commons candidate.

Listen deliberately at an already comfortable volume: original source, baseline
replay and sequence, isolated `u`, then candidate source/replay/sequence. Compare
with `drum`. Decide whether the baseline's issue comes from the original word or
the shared sound, and whether the candidate clearly gives /plʌm/ rhyming with
`drum` and fits the card. Automated integrity, metadata and ASR cannot approve this.

Options: approve this separately attributed speaker after listening; obtain a
suitable same-family GCompris recording with pinned source and credits; or make
a new explicitly licensed recording. No vowel splice or synthesized substitute
has been attempted. If the candidate is accepted, add its retained source and
license/credit to the pack, update only the affected source/edit metadata,
regenerate whole-word and sequence/cues with the documented production decoder,
and verify that unrelated audio/artwork and Math/Music bytes remain exact.
The correction and parent listening evidence are now recorded; issue closure and
delivery status remain with the integrating maintainer.

## Validation

```sh
PYTHONPATH=$PWD/src UV_CACHE_DIR=/tmp/tbx-release-uv-cache uv run --offline --no-project --python /tmp/toddlerbox-053/.venv/bin/python python -m pytest tests/test_reading_assets.py tests/test_reading.py
PYTHONPATH=$PWD/src UV_CACHE_DIR=/tmp/tbx-release-uv-cache uv run --offline --no-project --python /tmp/toddlerbox-053/.venv/bin/python python scripts/build-reading.py --verify
```

Initial investigation: 27 tests passed in 5.75s; source/output verification passed
for 214 sources and 290 prepared outputs, before changing product assets. Updated
integration checks are recorded below. No physical-appliance result, release
qualification or publication is claimed.

## Approved product integration (2026-10-31)

The parent approved both pronunciation and the different speaker. The product now
retains the original Commons OGG at `sources/word-plum.ogg` and its unnormalized
lossless decode at `sources/word-plum-pcm.wav`, SHA-256
`b2b4746137fe04c57b65649f1a8a77072be991fef331ae73e29bf3df763bead9`.
The superseded OGG remains byte-identical at `sources/word-plum-art4apps.ogg`,
with its original source record retained under `superseded_sources`.

The manifest's optional `decoded_pcm` record pins the lossless intermediate and
its decoder provenance. The builder verifies original, intermediate and archived
source hashes and reads the mono 44.1kHz signed 16-bit WAV directly before applying
its existing normalization, edit and sequence pipeline. This preserves the samples
the parent approved across OGG decoder versions without introducing a runtime
decoder or dependency. The new edit is `[0, 25600)`, with no trim. Source and output
attribution is in `assets/reading/licenses/Commons-plum-credit.txt` and the Reading
content README. Normal output provenance still points to `word-plum`, whose new
manifest entry carries the Commons attribution; its sequence also retains the
existing MIT sound-unit source IDs.

Recreate the intermediate before normal gain/assembly with the recorded existing
preview toolchain (Python 3.12.3, pygame-ce 2.5.8, SDL 2.32.10, SDL_mixer 2.8.2):

```sh
UV_CACHE_DIR=/tmp/tbx-release-uv-cache uv run --offline --no-project --python /tmp/toddlerbox-053/.venv/bin/python python - <<'PY'
import os, wave
os.environ['SDL_AUDIODRIVER'] = 'dummy'
import pygame
pygame.mixer.init(frequency=44100, size=-16, channels=1)
raw = pygame.mixer.Sound('assets/reading/sources/word-plum.ogg').get_raw()
pygame.mixer.quit()
with wave.open('assets/reading/sources/word-plum-pcm.wav', 'wb') as out:
    out.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
    out.writeframes(raw)
PY
```

The standard full pack rebuild remains `uv run python scripts/build-reading.py
--output build/reading-rebuild` with the documented ffmpeg toolchain for the
unrelated compressed sources. No full ffmpeg rebuild was attempted here because
ffmpeg is absent. The focused rebuild test uses the builder's actual PCM decoder,
normalization formula and byte encoding and matches the approved replay exactly;
the sequence test proves exact sound clips, gaps, complete replay and translated
cues. The historical preview script now reads genuine baseline media from commit
`4b9f6fb12f3718bb4d8ecffacb5ae518772b662d`, so rerunning it after integration
continues to reproduce the original comparison rather than relabeling new media
as baseline. The preview directory remains private to this local build and ignored.

Final commands were the same `uv` pytest/source verification commands above,
plus `git diff --check`, and a byte comparison of all paths returned by
`git ls-tree -r --name-only 4b9f6fb12f3718bb4d8ecffacb5ae518772b662d assets`
against `git show 4b9f6fb12f3718bb4d8ecffacb5ae518772b662d:PATH`.
Results:

- 32 Reading tests passed in 5.59s, including altered-intermediate hash rejection
  and incompatible channel/sample-width/rate rejection.
- Source/output verification passed (214 active sources, with the additional
  archived source and lossless intermediate also hash-checked; 290 outputs).
- 833 baseline asset files compared byte-for-byte; 825 unchanged. The eight
  modified existing files are the Reading README, plum source OGG, the two plum
  WAVs, and `catalog.json`, `edits.json`, `outputs.json`, `sources.json`.
- 287 of 290 prepared outputs remain exact. Only plum replay, plum sequence and
  catalogue hash changed. Every non-plum card record is identical; all artwork,
  Math, Music and unrelated audio bytes remain exact.
- Both product WAVs exactly match the approved preview WAVs and hashes above.
- New retained files are the attribution, old OGG archive and new lossless PCM.

Integration notes for the maintainer's shared changelog/contract: Reading now uses
parent-approved /plʌm/ whole-word audio, with a separately credited speaker; no
spelling, picture, phoneme clips, deliberate playback semantics or child UI change.
This development commit does not install, publish, close the issue, or qualify a
new release or physical device.
