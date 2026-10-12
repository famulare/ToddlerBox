# Changelog

## 0.5.1 - 2026-10-12

- Reading opens its selector in picture view and prepares bounded previews in the background instead of decoding in drawing.
- Photos preloads visible and upcoming thumbnail rows within its existing cache budget, including during a held touch. Restore loading ahead of the viewport without returning disk decoding to the UI thread.
- Math Next uses the whole button plus a small safe edge margin, and accepts the same 32-pixel release drift as Reading. No pressure threshold or appearance change.
- Manual piano notes sustain while held, then decay for 600 ms after release. Bounded sampled loops give the sustained note a stronger, consistent level without changing Reading/Math audio.
- Raise song body levels with offline 2× gain and smooth peak limiting, retaining piano headroom and original timing. Reading/Math recordings and settings remain unchanged.
- Prepare the fixed 25-key piano bank silently before input, removing first-touch file loading.
- Paint fill searches exact-color runs instead of Python pixels; opaque restored paintings fill correctly too. Fountain strokes reuse exact direction widths and already-painted caps without dropping input points.
- Paint/Typing New and recall archive immutable snapshots in one worker, preserving archive-before-clear durability while frames continue. Home and authenticated sync saves wait through normal frame polling; failed requests can be retried after storage recovers.
- Add a parent-only quiet, bounded PipeWire speaker check and explicit ALSA/PulseAudio diagnostic packages for future images. Existing installs need no new packages for the check.
- Physical touchscreen drag reliability still requires a retest; preloading alone is not claimed to resolve an unreproduced input-device failure.

## 0.5.0 - 2026-10-11

- Released piano notes decay for up to 600 ms; bounded overlapping voices keep song headroom. Home/focus still stops all audio immediately.
- Raise default song gain 4× and Reading/Math speech gain 2×; initialize child-session master volume predictably, retaining keyboard-only controls and the unity ceiling.
- Explicit authenticated parent opt-in applies louder defaults to existing installations while preserving other settings and backing up the original configuration.
- Parent-initiated USB Drive setup finds packages, verifies adjacent full SHA-256 automatically, preserves stable transfer inputs and shows results until dismissed.
- Fix connected Wi-Fi with broken DNS: NetworkManager uses connection-provided DNS directly; image and existing-install patch share the same policy.
- Reapply the source-checkout USB setup patch without reinstalling; existing work and credentials remain intact.
- Signed update-only release for existing Ubuntu appliances; separate authenticated source patch adds USB/DNS without expanding the resident updater's destinations. No new OS installer.

## 0.4.0 - 2026-10-05

- Math approved after Mac testing and integrated as the sixth offline activity.
- Three passive, tap-to-reveal number/arithmetic modes through 100, weighted per number and grouped into tens.
- Standard launcher: Paint/Photos/Music above Typing/Reading/Math; existing custom configuration is preserved.
- Pictures-first Numbers and on-demand offline speech for 0–100; no autoplay, scoring, learning history or object-tapping controls.
- Arithmetic speech reads the complete equation, including plus/minus and equals; interrupted audio cancels the remaining words.

- Music expands from six to eighteen public-domain piano arrangements; scrollable left song rail keeps Free Play, Pause and Autoplay reachable. Existing six performances and piano samples remain unchanged.
- Explicit GitHub build/VM qualification workflow keeps installer construction reproducible without using private family data.
- App bundle interpreter layout remains compatible with resident 0.3 installers while retaining their archive security guards.

## 0.3.0 - 2026-10-04

- Five offline activities with shared minimal styling and preserved illustrated icons.
- Music: six short piano arrangements, playable keys over songs, and Free Play.
- Reading: 75 illustrated words, child-paced phonics, word/picture selection, and no numbers or scoring.
- Durable Paint/Typing saves; bounded supervision and independent parent escape.
- Standalone Cage on Ubuntu 24.04 x86-64, firmware/network stack, tap-to-click and volume keys.
- Optional explicit-only private Drive copy sync, ordinary-file history and validated photo imports.
- Resumable authenticated parent setup, public signed updates, bounded candidate tests and independent boot recovery.
- Parent-initiated Ubuntu maintenance, sanitized reviewed support reports and reproducible installer/VM builds.
- See VALIDATION.md for release evidence and physical hardware limits.

## 0.2.0 - 2026-02-06

- Photos now sort newest-first by EXIF capture date when available.
- Photos without EXIF date fall back to file modified time (newest-first).
- Added screenshot gallery to README with inline GitHub-rendered images.
- Added `Pillow` dependency for EXIF metadata parsing.
- `pytest` is included in core dependencies for always-available test runs in the project venv.
