# Issue #30: deliberate visible-content speech

Implemented on `work/0.5.3-issue-30`, based on
`411f71294797b83569b63385bc072b870a114258` (development runtime plus agreed issue plan).
No release, installation or appliance qualification is claimed.

## Behavior and code boundary

Math uses the same fitted font and centered bounds for drawing and numeral hit
rectangles. Each printed numeral has an independent target padded by at least 16
horizontal and 12 vertical pixels (minimum 48×48 before clipping), clipped before
neighboring operator/question-mark centers and the question panel.
Operands speak their own values while the result remains hidden. Revealing is
silent; a subsequent tap on its visible numeral speaks it. Question marks have no
speech target. Objects remain passive. The existing speaker still reads the whole
revealed equation. Existing NumberPlayer cancellation replaces playback on every
numeral tap, including interrupted equations and missing clips. Next, mode and Home
retain their cancellation paths. No navigation/history work is included.

Reading's existing revealed-main-picture handler already cancels and replays the
whole word. Added regression coverage verifies this existing path, hidden-picture
inertness, repeated replay, touch/mouse deduplication and navigation cancellation;
no Reading production code changed.

## Baseline and validation

On the unchanged baseline module extracted with `git show HEAD:src/toddlerbox/math/app.py`,
a deliberate tap centered on the first operand in `8 + 2 = ?` set `revealed=True`
and never called `player.play`: the reported missing numeral behavior reproduced.
Reading's revealed-picture path was present in that baseline; no missing handler
was inferred or duplicated.

Python 3.12.3, pygame-ce 2.5.8, SDL 2.32.10; existing compatible test environment:

```sh
UV_CACHE_DIR=/tmp/tbx-release-uv-cache PYTHONPATH=$PWD/src \
  uv run --offline --no-project --python /tmp/toddlerbox-053/.venv/bin/python \
  python -m pytest tests/test_math.py tests/test_math_speech.py \
  tests/test_reading.py tests/test_reading_assets.py -q
```

Result: **125 passed**. `git diff --check` passed.

Frame evidence uses genuine old and new classes, the same synthetic cat motif,
fixed examples and both reveal states at 800×600, 1366×768 and 480×600. All 18
complete RGB frames matched byte-for-byte. Reproduce from the committed baseline:

```sh
git show 411f71294797b83569b63385bc072b870a114258:src/toddlerbox/math/app.py > /tmp/issue30-baseline-math.py
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  UV_CACHE_DIR=/tmp/tbx-release-uv-cache PYTHONPATH=$PWD/src \
  uv run --offline --no-project --python /tmp/toddlerbox-053/.venv/bin/python \
  python docs/dev/evidence/issue-30-frames.py
```

Focused tests cover hidden/visible zero and multidigit values, every Math mode,
non-overlapping fitted targets (minimum 48×48 across the tested sizes), separate
equal-valued operands, unchanged equation speech, silent transitions, missing
clips, real SDL cancel/replay, navigation cancellation and raw-finger plus emulated
mouse duplication. No child data or audio/image assets changed. Dummy SDL proves
application dispatch/cancellation, not audible playback or physical touch routing.
Standalone supervised child-session and physical hearing/touch validation remain
for the integrated candidate; current frozen artifact qualification is unchanged.

## Integration prose for parent

Contract Math speech paragraph: “A deliberate tap on a visible printed numeral
speaks that numeral's value, including equation operands before the result is
revealed. Revealing a hidden answer is silent; question marks never speak. Counting
illustrations remain passive. The separate speaker reads the revealed whole
equation. New examples and mode changes never start speech.”

README/activity guide: “Tap a printed Math number to hear it. Tap the question
panel to reveal an answer silently, then tap that answer to hear its number.
Reading's visible main picture replays the whole word.”

Changelog: “Math printed numbers now speak individually on deliberate taps,
including operands before answer revelation. Verified Reading's visible-picture
whole-word replay and duplicate-touch suppression; visuals remain unchanged.”

Current setup/update/build procedures do not change. Parent integration should
update shared README, contract and changelog and link this validation from the
combined VALIDATION.md, preserving standalone/physical qualification limits.
