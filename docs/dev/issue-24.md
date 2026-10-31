# Issue 24: Reading and Math visit history

Implemented against reviewed tap-to-speak baseline
`5dce023bcc34f3be7257e18b5c9e246de25994e4` on
`work/0.5.3-issue-24`. This change is development work, not a qualified appliance
release or authorization to close the issue.

Each app instance now owns a chronological, 100-entry in-memory history. Math
entries contain the immutable example (including mode and illustration motif)
and revealed flag. Reading entries contain the card identifier and revealed
flag. Entries contain no decoded pictures, audio, documents or archives.

Back restores the previous visit silently. Next traverses known forward visits
before generating another random example/card at the end; latest-entry selection
still excludes immediate repeats. Changing Math mode or choosing a Reading
sidebar card after Back replaces only the forward navigation branch. Reading's
Pictures/abc switch remains a presentation preference and creates no visit.
Leaving a visit captures its current reveal state. Navigation cancels playback
and pending pointer ownership/presses. A missing Reading card/image is skipped;
if no usable entry remains in that direction, current content and cursor remain
intact. Next can then choose fresh usable content. Oldest-entry Back is hidden
and harmless. Home behavior and its position remain unchanged.

The Back arrow uses the existing arrow/card styling in unused title-bar space,
with a 48×58 target. It leaves the existing equation speaker, fitted numeral
tap targets, passive Math objects, Reading sound units and main picture replay
unchanged. This change never touches child persistence or saved history files.

## Validation, 2026-10-31

Toolchain: Python 3.12.3, pygame-ce 2.5.8, SDL 2.32.10; existing frozen dependency
environment `/tmp/toddlerbox-053/.venv`, offline uv execution with
`UV_CACHE_DIR=/tmp/tbx-release-uv-cache` and the target source on `PYTHONPATH`.
No dependency or lockfile changes.

- Genuine unchanged baseline: 123 passed in 15.48 s for `test_math.py`,
  `test_math_speech.py`, and `test_reading.py` before editing.
- Final focused tests: 137 passed in 16.88 s for those suites plus
  `test_history.py` and `test_reading_assets.py`.
- Tests exercise history branch/capacity/edge rules, Math cross-mode exact
  example/motif and reveal restoration, Reading sidebar/presentation distinction,
  forward traversal, speech cancellation, stale releases, raw touch plus duplicate
  mouse, missing card/image recovery and narrow Math control placement. Existing
  numeral, equation, phoneme, no-immediate-repeat and rendering tests still pass.
- `git diff --check` passed.
- Genuine baseline/new frame comparison: all 18 frame pairs match at every pixel
  outside the intended Back rectangle. All six initial frames match completely.
  Each of the 12 later frames changes exactly 2,624 pixels within that rectangle.
  Sizes: 480×600, 800×600, 1366×768; both apps, initial/next hidden/next revealed.
  Only bundled illustrations and deterministic seeds were used. Thumbnails settled
  before capturing; no family media or private configuration was used.

[Comparison counts](issue-24/comparison.json), [baseline decoded RGB hashes](issue-24/baseline-frames.json),
[new decoded RGB hashes](issue-24/new-frames.json).

Synthetic screenshots:

| Size | Math | Reading |
| --- | --- | --- |
| 480×600 | [Math](issue-24/math-480x600-next-revealed.png) | [Reading](issue-24/reading-480x600-next-revealed.png) |
| 800×600 | [Math](issue-24/math-800x600-next-revealed.png) | [Reading](issue-24/reading-800x600-next-revealed.png) |
| 1366×768 | [Math](issue-24/math-1366x768-next-revealed.png) | [Reading](issue-24/reading-1366x768-next-revealed.png) |

To reproduce from this worktree (use a fresh temporary baseline directory):

```sh
mkdir /tmp/tbx-history-baseline
 git archive 5dce023bcc34f3be7257e18b5c9e246de25994e4 | tar -x -C /tmp/tbx-history-baseline
export UV_CACHE_DIR=/tmp/tbx-release-uv-cache
export SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy
PYTHONPATH=$PWD/src uv run --offline --no-project --python /tmp/toddlerbox-053/.venv/bin/python python -m pytest tests/test_history.py tests/test_math.py tests/test_math_speech.py tests/test_reading.py tests/test_reading_assets.py -q
PYTHONPATH=/tmp/tbx-history-baseline/src uv run --offline --no-project --python /tmp/toddlerbox-053/.venv/bin/python python docs/dev/issue-24-render.py /tmp/tbx-history-frames/baseline
PYTHONPATH=$PWD/src uv run --offline --no-project --python /tmp/toddlerbox-053/.venv/bin/python python docs/dev/issue-24-render.py /tmp/tbx-history-frames/new
PYTHONPATH=$PWD/src uv run --offline --no-project --python /tmp/toddlerbox-053/.venv/bin/python python docs/dev/issue-24-render.py --compare /tmp/tbx-history-frames/baseline /tmp/tbx-history-frames/new
```

No standalone child session, VM, physical touch/audio or hardware qualification
was performed here. Dummy SDL input/frame tests establish app behavior only.
The baseline, accepted live source and previously qualified VM disks remain
unchanged. Parent integration review and combined qualification remain required.

## Integration prose for shared documentation

For the Reading/Math design-contract sections, README activity descriptions and
changelog: “Reading and Math provide a Back arrow for up to 100 visits during the
current activity session. Next revisits known forward entries before choosing new
content. Math history crosses modes and restores the exact example and reveal
state; Reading's Pictures/abc switch changes presentation only. Revisiting content
is silent. A new card or Math mode after Back replaces the forward navigation
branch. No saved child work or archive is removed.”

Build, installation and update procedures are unchanged. The integration owner
should update shared documents together and record final combined source identity
and appliance qualification in VALIDATION.md. No publication, live installation,
issue closure or release claim was made by this task.

## Integration review follow-up: current-card selection

Repeated selection of the current Reading sidebar card retains the existing
silent reset: playback and pending input stop and its picture becomes hidden.
It updates the current history snapshot instead of creating a duplicate visit.
At an earlier entry it also preserves the known forward branch. Only choosing a
different card creates a new visit and truncates forward history. This
interpretation conflicts with no existing tests.

Regression tests exercise actual repeated sidebar clicks at the frontier and
after Back, checking reset/cancellation, unchanged history length/index, updated
reveal snapshot and Next restoring the existing forward card. The complete
focused command above passed again: **139 passed in 17.65 s**. `git diff --check`
passed. The original frame comparison remains applicable because the render path
and captured navigation sequence are unchanged.
