# ToddlerBox — Application and System Contract

This document is the source of truth for the ToddlerBox application and system contract.
The bootable system recipe and its qualification gates are documented in `system/README.md`.
Hardware qualification remains separate from application and VM tests.

## 0. Global invariants

- Language: Python 3
- UI framework: pygame / SDL
- Fullscreen, borderless kiosk-style UI
- Child-facing screens never show dialogs or crash traces
- Shared pygame theme: cream backgrounds, paper cards, dark ink, sage selection
  highlights, and the original illustrated icon family. The same 58px Home control sits at the
  top-right of every activity. Artwork/photo colors and saved data are independent
  of the interface palette.
- System parent escape: hold `Ctrl + Alt + Home` for two seconds; handled independently of the app
- Data root is configurable via `data_root` (defaults: dev `./data`, runtime fallback `/data`)
- Dedicated Cage child session; session-scoped inhibitors; normal GNOME controls in parent mode

## 1. Launcher

### 1.1 UX

- Fullscreen home view with five large app icons, in centered rows when needed:
  - Paint
  - Photos
  - Typing
  - Music
  - Reading
- Icon hit targets are computed from screen size (minimum 120px)
- Function keys `F1`-`F12` are ignored
- System image: deliberate parent chord reaches authenticated GNOME parent login
- Desktop development: launcher chord exits the application

### 1.2 App handoff model

- Built-in apps (`toddlerbox.paint`, `toddlerbox.photos`, `toddlerbox.typing`, `toddlerbox.music`, `toddlerbox.reading`) run embedded in-process.
- Launcher keeps a single pygame window and switches scenes to reduce transition flicker.
- Non-built-in commands are refused in the supervised child session; desktop development retains subprocess fallback.
- Subprocess fallback suppresses child stdout/stderr.

### 1.3 Return behavior

- App exits return to launcher home view.
- Pointer down/up events are cleared on return and pointer input is briefly debounced to avoid accidental relaunch.

## 2. Paint App

### 2.1 Layout

- Left tools panel + right canvas area
- Small Home button at top-right

### 2.2 Tools and controls

- Tools:
  - Round brush
  - Fountain pen (direction-sensitive width)
  - Eraser
  - Bucket fill
- Sizes: 3 presets (scaled by display)
- Palette: configurable; current config provides 14 colors
- Undo stack depth: 10
- Actions:
  - `New`: archive current canvas, clear canvas, clear undo
  - `Undo`
  - `Recall`

### 2.3 Persistence

- Stores in `data_root/paint/`
- `latest.png` autosaved periodically (default 10s)
- Archived snapshots named `YYYY-MM-DD_HHMMSS(.+counter).png`
- Atomic PNG replacement with file and directory fsync
- Existing `latest.png` is restored on app start; Home and termination attempt a save
- New clears only after successful archive; failures before replacement preserve the previous file. Directory-fsync failure after replacement reports uncertain durability of the new visible file.
- Periodic saves use one background snapshot and skip unchanged canvases. Input reset never postpones an outstanding save deadline.
- Archive limits are nondestructive capacities: Paint defaults to 100 and clamps zero to one. Full capacity refuses replacement without clearing work; quarantined corrupt files are excluded.

### 2.4 Recall UX

- Recall opens as a modal overlay in the left panel area
- Vertical scroll list of square thumbnails
- First thumbnail is current live canvas
- Remaining thumbnails are archived paintings (newest first)
- Tap-release selects; drag scrolls
- Tap outside closes recall
- Selecting archive loads it into canvas and promotes to `latest.png`

## 3. Photos App

### 3.1 Layout

- Vertical thumbnail strip on the left
- Main image area on the right
- Home button at top-right
- Optional next/prev arrows controlled by config (`photos.show_arrows`)

### 3.2 Behavior

- Library path: `data_root/photos/library`
- Thumbnail cache path: `data_root/photos/thumbs`
- Supported extensions: `.png .jpg .jpeg .bmp .gif`
- Thumbnails are generated/cached and reused by mtime
- Strip supports drag/wheel scrolling
- Tap-release on thumbnail selects image
- Horizontal drag in main image area changes image index
- EXIF orientation is applied consistently. One background worker prepares size-limited derivatives; a bounded thumbnail LRU avoids accumulating decoded images.
- Library refreshes on entry; source images over 40 million pixels are skipped with parent diagnostics.

## 4. Typing App

### 4.1 Layout

- Left controls panel, right text area
- Home button at top-right

### 4.2 Text model

- Rich per-character glyph model:
  - `char`
  - `size`
  - `style` (`plain|bold|italic`)
- Styling changes apply to newly typed characters from cursor forward
- Cursor and glyph rendering support mixed sizes/styles in one line
- Mixed-size line rendering is bottom-aligned per row
- Text area uses soft word wrapping:
  - Words wrap to the next line if they would overflow the text area width
  - A single word longer than the text area width is split across lines

### 4.3 Controls

- `New`: archive session and clear document
- `Undo`: depth 20
- Size buttons: default 25, plus 50 and 100
- Style buttons: Plain, Bold, Italic
- Recall button uses static thumbnail text prompt
- Cursor navigation:
  - Up/Down moves by soft-wrapped visual lines
  - View auto-scrolls to keep the cursor visible

### 4.4 Recall and persistence

- Current document: `data_root/typing/current.json`, saved every five seconds and on Home
- Current text, rich styling, and cursor are restored on app start
- Archives: `data_root/typing/archive/*.json`; legacy `sessions.jsonl` remains readable
- Each record stores:
  - `timestamp`
  - `rich_lines` (glyph arrays)
- Recall overlay opens in left panel and lists:
  - `Current`
  - Recent archived sessions (newest first)
- Each item shows text preview (first 150 normalized chars)
- Tap outside closes recall; tap-release loads selected session
- Layout is cached until text/style/width changes. Archive capacity defaults to 200 records/256 MiB, with no automatic deletion.
- Unsupported future save versions remain intact; this version uses a separate `current-v1.json` while that newer document exists.

## 4a. Music App

- Six bundled short piano arrangements with scores, synchronized cues and source/license notices under `assets/music/`.
- Fixed C3–C5 keyboard; falling bars encode pitch and held duration. Melody is blue, accompaniment gold. Piano touches do not play notes.
- Song choices, Play/Pause, Autoplay and Home are the only child controls.
- Entry starts the first song; selection starts/restarts that song. Autoplay defaults on and wraps with a quiet gap. Turning it off finishes the current song once.
- Pause freezes sound and visual time. One playback-position adapter drives the visualization, with configurable output-latency compensation.
- Home/TERM/exceptions stop and unload audio. No audio plays on the launcher or automatically resumes after a crash.
- Audio failure remains quiet, responsive and logged for the parent. Autoplay attempts each damaged track at most once until manual retry.
- Shared pointer ownership ignores duplicate SDL mouse events from touch and secondary fingers. Focus/scene changes discard stale input.

## 4b. Reading App

- One word, letter or numeral; tap to hear its recording(s), then reveal its picture.
- Word units are explicit: `ship` is `sh/i/p`, `duck` is `d/u/ck`.
- Word tap repeats the full sequence; picture tap repeats the whole word.
  In letter and number decks both targets repeat the selected sound/name.
- Uniform random Next excludes the current card. Recent earlier cards may return.
  A singleton deck supports replay; empty content returns Home quietly.
- No scores, time limits, rewards, automatic progression, spaced repetition or usage history.
- Parent YAML selects mode, word sets, letter sounds/names and case, or a number range within 0–30.
- Default: six short-a words, lowercase, software volume 0.35.
- Bundled pack: 30 words, 26 letter-sound cards, 26 letter-name cards, numbers 0–30.
  In phonics mode `q` is presented as `qu`; a written unit can represent multiple sounds.
- Pictures appear only after successful speech completion. No voices overlap or queue.
- Next/Home and focus/resume reset stop speech. Corrupt content is isolated; an unavailable
  device leaves the UI responsive and can be retried by a later deliberate tap.
- Asset paths, sizes, formats, cue bounds and durations are validated. Source recordings,
  source art, license terms and reproducible preparation records ship under `assets/reading/`.
- Playback is offline PCM; number speech is generated at preparation time. No runtime
  speech synthesis, new data schema or child-created Reading document is introduced.

## 5. Data layout

All app data lives directly under `data_root`:

```text
data_root/
├── paint/
│   ├── latest.png
│   └── YYYY-MM-DD_HHMMSS*.png
├── photos/
│   ├── library/
│   └── thumbs/
└── typing/
    ├── current.json
    ├── archive/
    └── sessions.jsonl  # legacy archives
```

## 6. Configuration (current keys)

- `data_root`
- `launcher.apps[]` (`name`, `icon_path`, `command`)
- `paint.autosave_seconds`
- `paint.palette`
- `photos.show_arrows` (optional)
- `paint.max_archives`, `typing.max_archives`, `typing.max_archive_bytes`
- `music.volume`, `music.autoplay`, `music.latency_ms`
- `reading.mode`, `reading.word_sets`, `reading.letter_case`, `reading.letter_audio`
- `reading.number_min`, `reading.number_max`, `reading.volume`

## 7. Error handling

- App `main()` wrappers catch exceptions, write diagnostic logs under `data_root/logs/`, and call `pygame.quit()` in standalone mode
- Embedded launcher path catches app exceptions, logs them, and returns to launcher
- Child-facing UIs do not show error dialogs
- Resume from sleep/focus changes clears stale pointer-drag state before normal interaction resumes

## 8. Bootable system

- Ubuntu 24.04 LTS, x86-64 UEFI; GDM is the sole graphical session manager.
- Separate child Cage and parent GNOME accounts/sessions.
- Event-loop heartbeats, bounded restart budget, persistent parent recovery latch.
- Boot-menu parent recovery and independent console access.
- Shared system disk for VM testing and USB installation.
- Versioned app environments; previous release retained during app updates.
- Cleanup acknowledgement and a bounded five-second grace precede forced termination; launcher identity is pinned with pidfds.
- Release changes are serialized and directory-synced, with declared data-schema compatibility. Rollback retains an identifiable previous target and requires parent mode.
- See `system/README.md` for exact behavior, artifact identity, and qualification limits.

## 9. Explicit private Drive copies

- Parent holds ctrl-alt-s for two seconds on one keyboard; no Shift required.
  One request per hold, rearmed by release. Ctrl+Alt+Home retains priority.
- Authenticated receipt is a quiet 48px shooting star left of Home for 1.5 seconds,
  fading over the last 0.3 seconds, on the launcher and all five activities.
  It confirms recognition, including offline/unconfigured/already-running states;
  it conveys no transfer outcome and never enters saved content or thumbnails.
- Root worker runs only on explicit request, with one job/transfer, low CPU/I/O
  priority, bounded retries, disk reserve and a 15-minute service timeout.
  No automatic boot/network/timer/watcher/restart-triggered sync exists.
- A credential- and process-checked save-current request uses the active app's
  normal save path. Wait at most five seconds, then stage stable durable files;
  missing/failed acknowledgement marks the result partial. Independent parent
  recovery and watchdogs remain effective during saves and stalled transfers.
- Credentials, persistent device UUID and sync state are root-owned and outside
  releases. Private setup packages are hash-verified, photos-only, repeatable and
  never overwrite newer child work. Parent restore adds Recall archives only.
- Directional copies: Photos down; Creations/device-UUID up; replaced cloud
  creations preserved under History/device-UUID/run-UUID. Initial originals have
  a verified Initial backup/date deposit. No deletion propagation or history pruning.
- Ordinary PNG/JPEG and authoritative Typing JSON plus UTF-8 text exports; no
  logs, thumbnails or temporary files. Unsafe paths/links, ambiguous names and
  unsupported nested photo imports are refused rather than silently flattened.
- Own Desktop OAuth client, Production consent, drive.readonly + drive.file.
  The read grant is account-wide; software pins operations to its rclone-created
  ToddlerBox root. Parent setup/status/reconnect are outside child UI.
- Targeted JPEG decoding may accept up to 80M header pixels only after decoder
  downsampling reduces allocation below the existing 40M decoded-pixel budget.
  Full-resolution and non-JPEG paths retain the 40M limit and bomb protections.
- See docs/drive-sync.md and docs/drive-sync-package.md for the public protocol.
