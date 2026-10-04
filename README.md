# ToddlerBox

**ToddlerBox 0.4:** six offline activities, a two-row launcher, pictures-first Math
with deliberate number speech, and 18 short songs in a scrollable Music library.

ToddlerBox is a minimalist, offline-first Linux "kid mode" designed for very young children.
The fullscreen launcher has six large buttons in two rows:

- **Paint**
- **Photos**
- **Music**
- **Typing**
- **Reading**
- **Math**

All six activities share a cream-and-sage interface and the same Home button.
The original illustrated icons are preserved; newer activities have matching icons.
Shared pygame styling lives in `src/toddlerbox/ui/theme.py`.

![Six-activity launcher and Math](docs/images/math-trial.png)

There is no desktop environment visible, no file browser, no login/logout flow, and no network dependency during normal use. The system is intentionally constrained, predictable, and robust against accidental input, while remaining easy for a parent to administer and extend.

This is not a general-purpose “kids OS.”
It is a small, comprehensible appliance built on top of Ubuntu.

---

## Design Goals

- **Appliance-like UX**
  - Power on -> launcher -> activity
  - No system UI exposed
- **Touch-first**
  - Large hit targets
  - No right-clicks, menus, or dialogs
- **Safe by construction**
  - Autosave everywhere
  - Undo everywhere
  - "New" never destroys work
- **Offline by default**
  - No network dependency during normal use
- **Parent-controlled escape**
  - Independent keyboard chord opens the parent GNOME login
- **Grow-with-the-child**
  - Built-in apps run in-process for smooth transitions
  - Supervised child sessions use registered embedded activities; development retains subprocess fallback
  - Full desktop can be re-enabled later without reinstalling

---

## Child session input

The bootable system runs Cage directly under GDM, with no surrounding GNOME
session. Child-session key inhibitors are released when entering parent mode.
Tap-to-click and hardware volume/mute keys are handled in the child session.
See [the HP controls patch](docs/child-controls.md) for updating an existing install.
Use [one parent update bundle](docs/updates.md) for app/system updates without
reinstalling Ubuntu or erasing child work.
The old global keyd setup is retired. See [system/README.md](system/README.md).

---

## High-level Architecture

```
┌────────────────────────────┐
│        ToddlerBox          │
│  (Fullscreen Launcher)     │
│                            │
│ [Paint] [Photos] [Music]   │
│ [Typing] [Reading] [Math]  │
│                            │
└─────────────┬──────────────┘
              │ switches scenes in-process
┌─────────────▼──────────────┐
│      Embedded App Views    │
│  - Paint                   │
│  - Photos                  │
│  - Typing                  │
│  - Music                   │
│  - Reading                 │
│  - Math │
│                            │
│  Fullscreen, no chrome     │
│  Exit = return to launcher │
└────────────────────────────┘

Underlying system:
- Ubuntu + systemd + Cage (Wayland kiosk compositor)
- Python 3
- pygame-ce / SDL
```

The launcher supervises apps. Apps exit cleanly back to the launcher. If an app crashes, the launcher simply reappears.

---

## Screenshots

### Launcher

Fullscreen home screen with large, simple app targets.

![ToddlerBox launcher](docs/images/math-launcher.png)

### Paint

Drawing canvas with kid-sized tools, palette, and autosave workflow.

![ToddlerBox Paint App](assets/screenshots/paint.png)

### Photos

Main photo view with left thumbnail selector strip and swipe navigation.

![ToddlerBox Photos App](assets/screenshots/photos.png)

### Typing

Large-format typing surface with per-character styling controls and recall.

![ToddlerBox Typing App](assets/screenshots/typing.png)

### Music

Eighteen short piano arrangements with a scrollable left song rail with song choices, autoplay, pause and a passive
falling-note keyboard with playable keys and Free Play. Audio and note cues are generated from the same score.

![ToddlerBox Music App](assets/screenshots/music.png)

### Reading

Tap each letter or sound group at your own pace. Tap the whole-word button
to hear the word and reveal its picture. Next chooses another random card without an immediate repeat.

![ToddlerBox Reading App](assets/screenshots/reading.png)

### Math

Three modes: pictures-first Numbers, Addition and Subtraction. Passive illustrated
ten-frames cover 0–100; a speaker button reads the revealed number on demand.
See [the design and desktop instructions](MATH_DESIGN.md).

---

## Components

### Launcher

- Standard home screen has six icons in two rows of three
- Runs built-in apps in-process (`paint`, `photos`, `typing`, `music`, `reading`, `math`)
- Subprocess fallback only in unsupervised desktop development
- No clickable "exit" control on-screen
- Ignores function keys (`F1`-`F12`)
- **Parent escape chord:** `Ctrl + Alt + Home`
  - Hold for two seconds in the system image to open the parent GNOME login

### Paint App

- Free drawing canvas
- Tools:
  - Round brush
  - Fountain pen (direction-sensitive width)
  - Eraser
  - Bucket fill
- 3 line-size options (small/medium/large)
- 14-color palette (configurable)
- Stroke-based undo (default depth: 10)
- Autosave + archive on "New"
- Recall overlay in the left tools panel:
  - First item is the current live canvas
  - Older archives below in a vertical scroll list
  - Tap outside recall closes it

### Photos App

- Photo library viewer
- Main image area + always-visible thumbnail strip on the left
- Swipe left/right to navigate
- Home button at top-right
- Photos are loaded from `data_root/photos/library`
- Thumbnail cache is stored in `data_root/photos/thumbs`

### Typing App

- Freeform text area with rich per-character styling
- Left control panel includes:
  - `New`, `Undo`
  - Font size buttons (`25`, `50`, `100`) with sample "A"
  - Font style buttons (`Plain`, `Bold`, `Italic`)
  - Recall thumbnail tile
- Styling changes apply to newly typed text from the cursor forward
- Undo and New supported (`Undo` depth 20)
- Recall overlay in the left panel shows saved session previews
- Current rich text saved periodically and on Home; restored on re-entry
- Sessions archived silently as individual JSON files; legacy `sessions.jsonl` remains readable

### Music App

- Mary Had a Little Lamb, Twinkle, Ode to Joy, Frère Jacques, Row Your Boat and Minuet in G
- Short piano arrangements, 21–33 seconds each, with quiet accompaniment
- Fixed two-octave keyboard: blue melody, gold accompaniment, held keys matching note cues
- Play keys over a song without interrupting it, or choose Free Play
- Select a song, pause/resume, or let autoplay continue through the collection
- Home and parent recovery stop playback; unavailable audio remains quiet and responsive
- Offline audio, scores, notices and reproducible generation recipe in [assets/music](assets/music/README.md)

### Reading App

- One large word or letter at a time; no automatic speech or advancement
- Tap each letter/sound group at your own pace; it plays only that sound
- Tap the smaller whole-word button to hear the word and reveal its picture
- A scrollable left rail switches between selecting written words and pictures
- Random Next excludes the current card; no scores, rewards, tests or learning history
- 75 illustrated words across short vowels, digraphs and consonant blends, plus alphabet sounds/names
- Defaults mix three-, four- and selected five-letter words; parent settings can narrow the deck
- Numbers and arithmetic stay separate in the Math application
- Next, Home, focus changes and parent recovery stop speech
- [Content credits and preparation](assets/reading/README.md); [design decisions](READING_DESIGN.md)

Paint and Typing archive limits are capacities, not automatic deletion policies.
At capacity, New/Recall replacement keeps current work and logs the reason for a
parent. Export or remove archives in parent mode to make space. Default capacities
are 100 Paint archives and 200 Typing archives/256 MiB; archiving also leaves a
16 MiB free-space reserve for current saves.

---

## Data Layout

All child-generated data lives under a single directory, configured by `data_root`:

```
/data/
├── paint/
│   ├── latest.png
│   └── YYYY-MM-DD_HHMMSS.png
├── photos/
│   ├── library/
│   └── thumbs/
├── logs/
│   ├── toddlerbox.log
│   └── toddlerbox.log.1
└── typing/
    ├── current.json
    ├── archive/
    └── sessions.jsonl  # legacy archives
```

- No file dialogs
- No delete UI
- Parent manages files externally if desired

---

## Configuration

Runtime configuration is read from `config.yaml` (repo root for dev) or `/etc/toddlerbox/config.yaml` (system image, selected by `KIDBOX_CONFIG`). Key settings:

- `data_root` (default dev config: `./data`)
- `launcher.apps` (icon paths + commands)
- `paint.autosave_seconds`
- `paint.palette`
- `paint.max_archives`, `typing.max_archives`, `typing.max_archive_bytes`
- `music.volume` (0–1, default 0.25), `music.autoplay`, `music.latency_ms`
- `reading.mode` (`words`, `letters`), `reading.word_sets`
- `reading.letter_case` (`lowercase`, `uppercase`), `reading.letter_audio` (`sounds`, `names`)
- `reading.volume` (0–1)

Reading settings are applied on activity entry. Word sets are `short_a_cvc`,
`short_e_cvc`, `short_i_cvc`, `short_o_cvc`, `short_u_cvc`, `digraphs`, and
`adjacent_consonants`. List multiple sets to mix them with equal chance per word.
For example, `reading: {word_sets: [short_a_cvc]}` narrows the deck to short-a
words. Change these YAML settings from parent mode; the child controls browse
the selected deck without changing its difficulty settings.

App-only updates preserve an existing `/etc/toddlerbox/config.yaml`. When upgrading
an older installation, add the Music and/or Reading launcher entries from this
repository's `config.yaml` in parent mode. Released 0.3.0 images include five apps;
0.4 adds Math as the sixth activity.

---

## Icons

Launcher icons are provided as pre-rendered PNGs with:

- Transparent background
- Normalized padding
- Multiple resolutions (256 / 512 / 1024)

They are stored in:

```
assets/icons/
```

---

## Development Setup

The primary target is the [bootable Ubuntu system](system/README.md), built
with `./system/build.sh` and tested with `./system/vm.sh`. See the
[validation record and remaining qualification](VALIDATION.md) before installing
it on hardware. The commands below run individual apps during development.

### Requirements

- Ubuntu 22.04 or 24.04
- Python ≥ 3.10
- SDL-compatible graphics (works on older Intel laptops)

### Dev environment (recommended)

Development uses `uv` with a local `.venv`:

```bash
uv sync --extra dev
```

## Convenience Script

```bash
./scripts/dev-run.sh
./scripts/dev-run.sh paint
./scripts/dev-run.sh photos
./scripts/dev-run.sh typing
./scripts/dev-run.sh tests
```

`scripts/dev-run.sh` is for development and exits on crash.

For kiosk-style resilience testing, use:

```bash
./scripts/run-stable.sh
```

`scripts/run-stable.sh` restarts the launcher automatically with bounded backoff if it exits unexpectedly.

---

## Running the Apps

From the repo root:

```bash
uv run python -m toddlerbox.launcher
uv run python -m toddlerbox.paint
uv run python -m toddlerbox.photos
uv run python -m toddlerbox.typing
uv run python -m toddlerbox.music
uv run python -m toddlerbox.reading
uv run python -m toddlerbox.math
```

---

## Bootable Ubuntu system

The development and deployment target is now the shared Ubuntu 24.04 x86-64
system recipe in [system/README.md](system/README.md). It produces a VM disk and
USB installation media from the same assembled filesystem.

```bash
./system/build.sh
./system/vm.sh start
```

GDM starts a standalone Cage child session. Hold `Ctrl+Alt+Home` for two seconds
to reach the separate parent account's GNOME login. An independent controller
handles that chord and bounded crash/hang recovery. The boot menu also provides
parent recovery. First boot asks you to create the parent password, then opens
authenticated parent setup for network, audio, input and recovery checks.
Use **ToddlerBox Setup & Maintenance** for public signed updates, rollback,
Ubuntu maintenance and reviewed support reports. No Git credentials or manual
release-hash checks are needed. See [parent maintenance](docs/parent-maintenance.md).

See the system guide for prerequisites, graphical VM inspection, installation,
release rollback, and qualification limits. The former tty-autologin, GDM-masking,
and global keyd setup scripts are retired.

---

## Tests

```bash
uv run pytest
```

---

## Project Status

This is a personal project built for a real child on real hardware.
The emphasis is on **clarity, durability, and restraint**, not feature count.

Contributions are welcome if they respect the core design principles.

---

## License

Application code: MIT. Bundled media have separate source and license notices
under [assets/music](assets/music/README.md) and [assets/reading](assets/reading/README.md).

## Optional private Drive copies

A parent can request an offline-first, copy-only Drive transfer by holding
**ctrl-alt-s for two seconds**. The shooting star confirms receipt only; parent
status reports the result. There are no automatic sync jobs. See
[setup and operation](docs/drive-sync.md), the
[private package format](docs/drive-sync-package.md), and the
[privacy and Google permission explanation](docs/drive-sync-privacy.md).

---

For Rosemary.

Music's left song list scrolls by touch or wheel, with Free Play always visible.
![Expanded Music library](docs/images/music-library.png)
