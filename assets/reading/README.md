# Reading content and preparation

This pack is entirely offline: 30 illustrated words, 26 letter-sound cards,
26 letter-name cards, and 31 number cards (0–30). Normal image builds copy the
prepared PNG/WAV files. The installed app never downloads or synthesizes speech.

## Credits and licenses

The application code is MIT licensed. Media retain their individual terms:

| Content | Source | Terms |
| --- | --- | --- |
| Phoneme recordings | Debbie Dann, [Buzzphonics](https://github.com/hellodeborahuk/buzzphonics), 2022 | MIT; upstream explicitly licenses the phonics sounds |
| Most whole words | Smart4Kids / Art4Apps, 2011, distributed by [GCompris](https://invent.kde.org/education/gcompris-data) | CC BY-SA 3.0; original OGG tags and upstream words/README retained as evidence |
| Additional whole words and letter names | Joshua Shreve, GCompris, 2019 | GPL 3.0 or later, as identified by upstream credits and OGG tags |
| Outlined illustrations | [OpenMoji contributors](https://openmoji.org/) | CC BY-SA 4.0; rendered from the pinned original SVGs |
| Additional illustrations | ToddlerBox, 2026 | MIT; original SVGs included |
| Number recordings | Generated for ToddlerBox using Piper 1.4.2 and the LJ Speech medium voice | Generated audio under the project MIT license; voice repository declares MIT, training dataset is public domain |

Full source URLs, immutable revisions, SHA-256 hashes, credits and per-file
licenses are in `sources.json`. Original recordings and vector drawings are in
`sources/`. License texts and source declarations are in `licenses/`. The number
voice's pinned model identity, settings and generated source hashes are in
`sources/numbers-provenance.json`; the large model is not bundled.

`outputs.json` maps each prepared file to its source IDs, hash and license.
Word sequences combine the whole-word recording with MIT phoneme clips and
silence. Each resulting sequence retains the whole-word recording's applicable
CC BY-SA 3.0 or GPL 3.0-or-later terms. The originals and preparation scripts
provide the corresponding editable sources. Keep these credits, source files
and license texts when distributing the pack. Pictures were scaled/rasterized;
recordings were resampled, trimmed, gain-adjusted and, for sequences, assembled.

The recordings include different speakers and British/US English pronunciations.
Letter names come from the US English collection; the isolated sounds are from
Buzzphonics. Filenames and automated decoding checks do not establish teaching
quality. Human listening and pronunciation review remain required; no such
review is claimed by the automated tests. Replace an unsuitable recording through
this content pipeline rather than changing playback code or substituting a
letter name for a sound.

## Rebuilding

From the repository root, using uv:

```bash
uv run python scripts/build-reading.py --verify
uv run python scripts/build-reading.py --output build/reading-rebuild
```

Preparation was verified using Python 3.12, pygame-ce 2.5.8 / SDL 2.32.10 and
ffmpeg 7.1.5-0+deb13u1. The project `uv.lock` pins the pygame/Pillow environment.
Use the same decoder version when comparing exact output bytes. Ordinary
Ubuntu builds do not execute this preparation step and need none of its tools.

The script checks source hashes before processing, applies the explicit edit
bounds in `edits.json`, converts to mono 44.1kHz 16-bit PCM, and normalizes with
a bounded gain and peak headroom. It writes matching highlight cues from the
same sample sequence. Initial edit suggestions retain 100ms around detected
speech; silence detection is not a substitute for listening. The originals are
preserved. `--prepare-trims` is a maintainer action to refresh those explicit
bounds after changing content, not a step in ordinary builds.

To regenerate the optional number source recordings, obtain the hash-checked
model/config named in `scripts/prepare-reading-numbers.py`, then run:

```bash
uv run --locked scripts/prepare-reading-numbers.py --model-dir /path/to/pinned/model
```

This separate Python 3.12 preparation environment is locked by
`scripts/prepare-reading-numbers.py.lock`. Its CPU inference uses zero noise.
Whole names such as “twenty one” are synthesized in one utterance. The script
does not download anything itself. The checked-in number WAVs let every normal
build work without the voice model or inference libraries. Piper's engine is
GPL licensed; it is used only as a preparation tool and is not shipped in the
ToddlerBox runtime.

The app validates the versioned catalog, cue bounds, image sizes and PCM headers,
and skips damaged entries. It retains no learning history or scores.
