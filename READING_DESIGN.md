# Reading: design and implementation

Reading is the fifth embedded ToddlerBox activity. It supports exploration with
Rosie and a parent, without scores, rewards, timers, assessment or automatic
progression. Numbers and arithmetic are reserved for a separate future activity.

## Interaction

A large word appears with its main picture hidden. Each letter or grouped sound
is a separate tap target: one tap plays that sound, and a later tap interrupts it
rather than queuing more speech. No other letters or whole word play automatically.
A small button bearing the word plays the natural whole-word recording and reveals
its picture only after successful completion. A revealed picture repeats that
recording. Letter mode uses the same distinction: large-letter taps play the
selected sound/name without revealing; the deliberate name button reveals.

A minimal scrollable left rail offers direct selection. Its `abc`/`Pictures`
toggle selects written words or picture previews; choosing Pictures deliberately
makes those hints available. Scrolling cancels selection when a drag is detected.
The main picture remains hidden after card selection. Next chooses uniformly
among usable enabled cards except the current one; returning to a recent card
is allowed. There is no spaced repetition, rotation, learning history or scoring.

Home, Next and focus changes stop speech and stale input. Cancelled, prematurely
ended or stuck recordings do not reveal a hidden picture. The shared cream,
paper, ink and sage theme and original illustrated launcher icons are retained.
Family names/photos and picture-choice exercises remain future work.

## Content and configuration

The offline pack includes 75 illustrated words across seven sound-pattern groups,
26 letter-sound cards and 26 letter-name cards. Defaults enable all word groups:

```yaml
reading:
  mode: words
  word_sets: [short_a_cvc, short_e_cvc, short_i_cvc, short_o_cvc,
              short_u_cvc, digraphs, adjacent_consonants]
  letter_case: lowercase
  letter_audio: sounds
  volume: 0.35
```

Parents can narrow groups in YAML, choose letters, uppercase or letter names.
Difficulty follows sound patterns rather than character count: `ship` uses
`sh/i/p`, `egg` uses `e/gg`, `frog` has four sounds and the later groups include
`brush`, `stamp` and `plant`. These are curated examples, not a claim that each
letter has only one sound. Sound mode presents `q` as `qu`.

Invalid settings fall back quietly to defaults with a parent diagnostic. Legacy
numbers mode falls back to words. Fresh installations use the expanded defaults;
app-only updates preserve existing parent configuration. Software volume is
bounded to 0–1; actual loudness remains a hardware check.

## Media and licensing

Phonemes are human recordings by Debbie Dann/Buzzphonics, MIT licensed. Whole
words and alphabet names use pinned GCompris sources with per-file CC BY-SA 3.0
or GPL 3.0-or-later attribution. Pictures use pinned OpenMoji, CC BY-SA 4.0,
and original MIT ToddlerBox SVG drawings. The bun and stick-gum pictures are
original drawings to make their word correspondence clearer.

[The asset README](assets/reading/README.md) records sources, immutable revisions,
hashes, license copies, credits and preparation commands. Checked-in outputs
make ordinary system builds independent of content downloads, ffmpeg or speech
inference. Maintainer preparation preserves originals and versioned trim bounds.
The recordings include multiple speakers and British/US pronunciation. Automated
checks cover integrity, format, duration and sound cues; human listening remains
necessary for pronunciation and suitability.

Prepared sequence WAVs are a source of bounded sound slices, with cue offsets
from the same PCM assembly. The app plays only the requested slice or the
separate whole-word/name recording. It does not run those sequences automatically
or attempt synthesized continuous coarticulation.

## Implementation and recovery

`catalog.py` validates bounded card data, unit coverage, cues, confined paths,
PNG dimensions and PCM payloads. `selection.py` selects uniformly without an
immediate repeat. `playback.py` owns the SDL music stream and cancels, detects
early completion and bounds stuck playback. Sound taps create a bounded in-memory
WAV containing the validated requested PCM slice. Untagged end events cannot
reveal an old card after selection changes.

`app.py` handles single-pointer controls, owned scrolling and the shared Home
control, then reports frame health. Images and visible rail thumbnails are
bounded by the finite checked-in pack. Cleanup runs in a `finally` path. Corrupt
cards/recordings yield parent logs and quiet child recovery; device failures allow
a later deliberate retry. No child error dialogs or learning records are added.
Independent parent escape and the controller watchdog remain the hang recovery
route. Reading writes no child work and introduces no work-data migration.

## Validation

Tests exercise actual PCM slices, child-paced sounds, delayed reveal, random
selection, malformed media, early/stuck audio, missing devices, cancellation,
rail rendering/scrolling and layouts from 800×600 upward. Compare real baseline
and current rendering under identical inputs; unchanged Paint, Photos, Typing,
launcher, saved outputs and existing media must remain equal. Independent review,
image/VM evidence and hardware/listening limits are recorded in `VALIDATION.md`.

The [DfE Reading Framework](https://www.gov.uk/government/publications/the-reading-framework-teaching-the-foundations-of-literacy)
informs sound/letter relationships and avoiding picture guessing. It is school
guidance, not validation of this toddler app; delayed hints and no scoring are
ToddlerBox choices for Rosemary.
