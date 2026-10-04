# Reading content and preparation

This pack is entirely offline: 75 illustrated words, 26 letter-sound cards,
and 26 letter-name cards. Numbers/math are reserved for a future separate app. Normal image builds copy the
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

Full source URLs, immutable revisions, SHA-256 hashes, credits and per-file
licenses are in `sources.json`. Original recordings and vector drawings are in
`sources/`. License texts and source declarations are in `licenses/`.

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

The expansion fetch script uses the same immutable GCompris/OpenMoji revisions,
retains per-file credits and includes editable original drawings. Rebuilding the
prepared pack works offline once these checked-in sources are present. Grouped
letters such as `sh`, `ck` and `ll` are one tapped sound; each tap extracts the
exact bounded PCM cue from its checked-in sequence. The UI does not autoplay the
sequence. Only a deliberate whole-word/name playback reveals the main picture.

The app validates the versioned catalog, cue bounds, image sizes and PCM headers,
and skips damaged entries. It retains no learning history or scores.
