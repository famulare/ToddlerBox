# Math application

Math was tested on Mac in PR #9 and approved for integration. ToddlerBox 0.4
includes it in the standard six-activity launcher and qualified installation.
The original trial and follow-up evidence remain in VALIDATION.md.

## Interaction

Three modes cycle through one compact top control: `Numbers`, `+`, `−`.
Home and Next retain the shared style. Tap the large number/question card to
reveal. Objects are visual only: tapping them has no action. There is no left
rail, answer entry, right/wrong feedback, scoring, progression or learning history.

- **Numbers:** objects first; tapping the `?` card reveals their numeral.
  The objects stay visible afterward.
- **Addition:** `A + B = ?` above two collections; tapping reveals C and a third
  collection regrouped into tens.
- **Subtraction:** `A − B = ?` with A colored objects; tapping marks the last B
  positions with muted gray ghosts and cancellation strokes, then shows the C
  remaining objects regrouped in a separate result area.

The result remains visible until Next or mode change. Mode changes and Next
discard stale pointer ownership. Focus changes and long frame gaps also discard
input, so an old release cannot reveal a new question. In development, Home
returns to the launcher (or closes standalone Math).

A small speaker button appears after revelation. Each deliberate tap reads the
disclosed numeral (Numbers) or complete equation (arithmetic), replacing current
speech. For example, `8 - 3 = 5` reads "eight minus three equals five".
Nothing plays automatically and playback never reveals or changes an example.
Home, Next, mode changes and focus changes stop and unload the clip. A duration
deadline bounds a stalled stream; unavailable audio leaves visual use intact and
device failures can be retried by tapping again. All 101 complete number names
and the three words plus/minus/equals are bundled as bounded PCM WAVs. The five
equation clips are validated before playback; an early stop cancels the rest.
There is no network, runtime synthesis or new runtime
dependencies. See [audio preparation and provenance](assets/math/README.md).
Pronunciation and output loudness still need parent listening on the HP.

## Quantities and random selection

The default range is **0–100** from the start. Every quantity uses ten-frames:
two rows of five, filled in fixed row-major order, with complete tens and a final
partial frame. Zero is an empty frame; hidden objects instead show a neutral
question area. Exactly 100 occupies ten complete frames. Arithmetic uses the
same illustration size across all its collections.

An explicit allowlist selects one-object Reading illustrations: cat, dog, pig,
hen, fish, frog, egg, bun, crab and ant. One motif is used throughout an example.
Its PNG bytes are unchanged; runtime cropping and bounded scaling improve small
display readability. Retain [Reading's sources, credits and license terms](assets/reading/README.md).
No new image downloads, UI frameworks or runtime synthesis are required.
PNG file size, format, dimensions and CRCs are checked before SDL decoding;
damaged motifs are skipped while other usable illustrations remain available.

Each integer 0–20 has weight **12**; each integer 21–100 has weight **1**.
The unrestricted number distribution is 252/332 (75.90%) low and 80/332 (24.10%)
high. This is a *per-number* ratio, not a 12:1 ratio between the two bands.

Addition weights the total T and divides its weight equally among T+1 ordered
splits. Subtraction weights starting total A and divides its weight equally among
A+1 amounts to remove. Addition totals never exceed 100; subtraction cannot be
negative. Crossing tens is included, including `8+7` and `23−8`.

Next excludes the current numerical prompt regardless of drawing, then samples
the finite remaining distribution without rejection loops. Relative weights are
preserved after exclusion; the overall band proportions can therefore change
slightly. Swapped addition operands are different displayed prompts. No per-mode
history is retained. A parent-configured singleton range hides Next.

```yaml
math:
  mode: numbers        # numbers, addition, subtraction
  max_number: 100      # optional parent setting, 0–100
  low_number_weight: 12
  volume: 0.35         # optional, clamped to 0–1
```

## Launcher and configuration

The standard launcher explicitly uses two rows of three, even on a wide screen:

| | | |
|---|---|---|
| Paint | Photos | Music |
| Typing | Reading | Math |

Fresh defaults have this arrangement. Exactly recognized historical five-app
configurations are augmented and reordered in memory, without rewriting their
files. Custom lists, ordering, paths, commands and deliberate omissions remain
unchanged. Existing data paths and private configuration are preserved.

## Runtime and validation

Math is an embedded activity using the existing single-pointer helpers, frame
heartbeat, independent production parent recovery and authenticated control
channel. It writes no child work. Its normal run loop acknowledges save-current
through the existing no-work path and draws the screen-only sync receipt before
the display flip. No controller, installer or update protocol changes are made.

Pure tests cover finite distributions, all 5,151 possible prompts per arithmetic
mode, conditional repeat suppression, invalid configuration, zero and ten-frame
geometry. Focused pixel checks cover hidden values, ghost removal, result
revelation, input cancellation, cache bounds and the actual control/flip order.
Native screenshots include dense arithmetic at 800×600 and 1366×768. Baseline
comparisons use genuine released code and identical fixtures; only the launcher
is intentionally different. Evidence and limits are in `VALIDATION.md`.

## Teaching references

- [GCompris activities](https://gcompris.net/screenshots-en.html): counting,
  quantities and arithmetic. The inspected activity sources at
  `f693b71be92e6d1f5261a0162b15d00d413d186a` are GPL-3.0-or-later;
  the complete suite includes an AGPL dependency. No activity code is copied.
- [Number Frames](https://www.mathlearningcenter.org/apps/number-frames) and
  [Number Pieces](https://www.mathlearningcenter.org/apps/number-pieces): teaching
  references for grouping and regrouping. No code or media is redistributed.
- [Sugar Abacus](https://github.com/sugarlabs/activity-abacus): an open-source
  arithmetic manipulative; GTK/Sugar dependencies make it a different runtime.
- [Teaching Math to Young Children](https://ies.ed.gov/ncee/wwc/PracticeGuide/18):
  developmental number/operations guidance, not evidence validating this app.

## Mac trial

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed.
Use a separate checkout to keep your released checkout and work untouched:

```bash
git clone https://github.com/famulare/ToddlerBox.git ToddlerBox
cd ToddlerBox
uv sync --frozen --group dev
uv run --frozen python -m toddlerbox.launcher
```

For Math alone: `uv run --frozen python -m toddlerbox.math`.
The checkout defaults to its own `./data`. Run from its repository root so all
existing artwork resolves. An inherited `KIDBOX_CONFIG` overrides that default;
unset it for this isolated trial if it points at your private installed config.

Try the six-tile ordering, all three modes, reveal versus inert object taps, Next,
mode changes, speaker replay/stop and Home. Check small counts, zero, crossing tens and dense 100-object
displays for clarity. The app has no difficulty lock.
The user reported the first trial functional on Mac; the new speech and ordering
need another Mac listening/input pass. Automatic tests ran on Linux. The focused portable suite is:

```bash
uv run --frozen pytest -q tests/test_math.py tests/test_math_speech.py tests/test_config.py tests/test_launcher.py
```

The authenticated Linux IPC test skips on Mac; this does not weaken production
authentication. The full controller suite uses Linux-only APIs and is not a Mac
compatibility test. Desktop testing complements the separate Ubuntu installer qualification.

The first trial's `numerals` and `count` configuration names both map to `numbers`
in memory without rewriting the configuration. The redundant numeral-first mode
was removed following Mac user feedback. Objects remain passive.
