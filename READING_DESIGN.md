# Reading: design and implementation

Reading is the fifth embedded ToddlerBox activity. It offers exploration alongside
reading with a parent, without assessment, rewards, timers or automatic progression.
Implementation and the content pack are complete; validation evidence and remaining
hardware/listening limits are recorded in `VALIDATION.md`.

## Interaction

One large word appears, with its picture initially hidden. Tap the word to hear
its constituent sounds, highlighted left to right, then a naturally spoken whole
word. Reveal the picture after successful completion. The written word stays in
the same place. Tap the picture to repeat the whole word; tap the word to repeat
the full sequence. A previously revealed picture remains during replays.

Next selects uniformly among enabled, usable cards except the current one.
`cat → map → cat` is allowed. Selection has no rotation, spaced-repetition state,
scoring, progress estimate or learning history. Two cards alternate; one card
supports replay with Next absent. Empty content quietly returns Home. The last
card ID is held only in the current process to avoid immediate repetition on
activity re-entry; a fresh boot starts a new random session.

Only the word/picture, Next and the common Home control are interactive. Individual
letter tapping, picture-choice exercises, family names/photos and a child-facing
level selector are deferred. While sound plays, extra taps do not queue speech.
Next/Home interrupt it. Focus changes and suspension gaps cancel playback and
stale input. A cancelled or prematurely ended recording does not reveal a picture.

Reading uses the shared cream/paper/ink/sage theme and original illustrated icon
family. The new book icon matches the approved glossy launcher icons. Vocabulary
pictures use simple outlined art. At smaller sizes, the launcher centers its five
icons in rows while preserving their order and minimum 120px targets.

## Content and configuration

Parents edit the existing YAML configuration; it is read on activity entry. No
new settings application is introduced. The default is:

```yaml
reading:
  mode: words
  word_sets: [short_a_cvc]
  letter_case: lowercase
  letter_audio: sounds
  number_min: 0
  number_max: 20
  volume: 0.35
```

Modes are `words`, `letters`, and `numbers`. Uppercase and letter names are parent
options. Number bounds must be within 0–30. Software volume is bounded to 0–1;
actual speaker loudness needs an HP check. Invalid options fall back to defaults
with a parent diagnostic.

| Word set | Included words |
| --- | --- |
| `short_a_cvc` | cat, hat, mat, map, cap, pan |
| `short_e_cvc` | bed, hen, net, pen |
| `short_i_cvc` | pig, bib, wig, lip |
| `short_o_cvc` | dog, log, pot, top |
| `short_u_cvc` | mug, sun, bus, bug |
| `digraphs` | ship, fish, duck, sock |
| `adjacent_consonants` | hand, tent, frog, drum |

A parent can combine any sets; mixed selection has equal probability per card.
Difficulty follows sound patterns rather than character count. `ship` highlights
`sh/i/p`, `duck` uses `d/u/ck`, and `frog` retains four separate sounds. Do not infer
segmentation by splitting every word into individual characters. `bib`, `wig`, and
`mug` replaced three draft words to use recordings with documented provenance.

The alphabet has 26 sound cards and 26 name cards, filtered by the parent setting.
Sound mode presents `q` as `qu`; `x` can represent multiple sounds. These are
curated common examples, not a claim that each letter always has one sound.
Letters reveal an illustrated example; either tap target repeats the selected
letter sound/name. Speaking the example word is not part of this first version.

Numbers have 31 complete-name recordings. Their quantities appear in stable
2×5 frames, up to three frames for 30. Zero shows an empty frame. Number naming
is a separate recognition activity, not word-decoding practice.

## Asset decisions

- **Phonemes:** human recordings by Debbie Dann from Buzzphonics, explicitly MIT
  licensed. The React application and its separately licensed illustrations are
  not imported.
- **Whole words:** GCompris's current English collection provided the broader
  vocabulary. Most chosen recordings are Art4Apps/Smart4Kids, CC BY-SA 3.0;
  additional recordings and alphabet names are Joshua Shreve, GPL 3.0 or later.
  Per-file source evidence determines the terms, not the code repository's license.
- **Numbers:** existing human number recordings stopped at 20. All 0–30 names use
  one fixed Piper/LJ Speech voice, generated at preparation time. A complete name
  such as “twenty one” is one utterance. No runtime model or speech service ships.
- **Pictures:** OpenMoji CC BY-SA 4.0 plus original ToddlerBox SVG drawings. Original
  vectors, recordings, license copies, credits and modifications are included.
- **Feed the Monster:** useful during research, but its checked English folder
  covered only 12 draft words and its README's audio license statement did not
  specify the CC-BY version. No Feed the Monster assets are bundled.

Sources, immutable revisions, hashes, derived-file licenses and the exact
preparation commands are in [assets/reading/README.md](assets/reading/README.md).
The original recordings and number WAVs are checked in, so normal system builds
need no content downloads, ffmpeg, Qt or speech inference environment.

The recordings include multiple speakers and British/US English pronunciation.
Automated checks verify decoding, bounded length, file integrity and cue structure;
they cannot certify pronunciation quality. Human listening remains outstanding.
Initial audio edit bounds retain 100ms around detected speech and are explicit,
versioned data. Preserve originals and inspect releases and vowels when listening.
Do not replace an unsuitable phoneme with a generic TTS reading of a letter name.

Word sequences combine the sound recordings, 150ms gaps, then a 400ms pause and
the complete word. Highlight cues come from the same PCM assembly. This demonstrates
segmentation followed by a whole word; it does not synthesize natural continuous
coarticulation. Listening may justify changing the pauses or recording whole
purpose-made demonstrations without changing the app architecture.

## Implementation and recovery

`reading/catalog.py` validates bounded catalog data, text/unit coverage, cue
bounds, confined asset paths, PNG dimensions and PCM format/payload length.
`selection.py` makes one uniform draw from a deduplicated candidate list.
`playback.py` owns one SDL music stream and its idle/playing/revealed/unavailable
state. It polls the audio position, rejects early completion, and times out a
stream that exceeds its declared duration. Untagged SDL end events cannot cause
an old card to reveal after Next.

`app.py` renders the fixed layout and quantities, handles release-based taps with
shared single-pointer ownership, drops stale focus input and reports frame health.
Next stops sound before loading the next image. Cleanup runs in a `finally` path;
the process-wide mixer and display remain owned by the shared application.

Corrupt entries are excluded with parent diagnostics. A damaged recording is not
retried automatically; a device failure permits a later deliberate retry. Home
and Next remain responsive. No child dialogs, error traces, score files or
learning history are created. The existing independent parent chord and watchdog
remain the final process-hang recovery route. Other activities retain their own
save/restore behavior; Reading introduces no data migration.

All five activities share the existing window and embedded launcher. The system
recipe copies the same application and assets into the versioned release, VM
image and USB installer. No alternate installation path is introduced. App-only
upgrades preserve parent configuration, so older launcher lists need Reading's
entry added explicitly; fresh images include it.

## Validation requirements

Behavioral tests cover random candidate selection, duplicate/empty/singleton
cases, sequencing/reveal, rapid taps, duplicate touch-emulated input, second
fingers, focus loss, Next/Home cancellation, exception cleanup, malformed content,
missing devices, early-ended/stuck streams and layouts from 800×600 upward.
Content tests check all selectable decks, explicit digraph/cluster mappings,
source/output hashes and bounded non-silent PCM. Preparation is rebuilt separately
and compared with committed outputs.

The system check boots and installs the actual x86-64 Ubuntu image, opens Reading
through the child launcher, captures speech and silence after exit, exercises all
three modes, and verifies independent recovery while speech is active. HP touch,
speakers, sleep/resume and human listening remain a separate bounded qualification.
Record completed checks and limitations in `VALIDATION.md`; do not equate dummy
SDL audio with audible output or VM capture with physical speaker quality.

The phonics principles draw on the [DfE Reading Framework](https://www.gov.uk/government/publications/the-reading-framework-teaching-the-foundations-of-literacy):
explicit sound/letter relationships, blending and avoiding reliance on pictures
to guess words. This is school guidance, not validation of this toddler app.
Delaying the picture and omitting scoring are ToddlerBox choices for Rosemary.
