# ToddlerBox

**ToddlerBox** is a minimalist, offline-first Linux "kid mode" designed for very young children.
By default it boots into a fullscreen launcher with three large buttons:

- **Paint**
- **Photos**
- **Typing**

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
  - Non-built-in apps can still be launched via subprocess fallback
  - Full desktop can be re-enabled later without reinstalling

---

## Child session input

The bootable system runs Cage directly under GDM, with no surrounding GNOME
session. Child-session key inhibitors are released when entering parent mode.
The old global keyd setup is retired. See [system/README.md](system/README.md).

---

## High-level Architecture

```
┌────────────────────────────┐
│        ToddlerBox          │
│  (Fullscreen Launcher)     │
│                            │
│  [ Paint ] [ Photos ]      │
│          [ Typing ]        │
│                            │
└─────────────┬──────────────┘
              │ switches scenes in-process
┌─────────────▼──────────────┐
│      Embedded App Views    │
│  - Paint                   │
│  - Photos                  │
│  - Typing                  │
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

![ToddlerBox Launcher](assets/screenshots/launcher.png)

### Paint

Drawing canvas with kid-sized tools, palette, and autosave workflow.

![ToddlerBox Paint App](assets/screenshots/paint.png)

### Photos

Main photo view with left thumbnail selector strip and swipe navigation.

![ToddlerBox Photos App](assets/screenshots/photos.png)

### Typing

Large-format typing surface with per-character styling controls and recall.

![ToddlerBox Typing App](assets/screenshots/typing.png)

---

## Components

### Launcher

- Fullscreen home screen with three icons
- Runs built-in apps in-process (`paint`, `photos`, `typing`)
- Subprocess fallback for non-built-in commands in config
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
parent recovery. First boot asks you to create the parent password.

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

MIT
