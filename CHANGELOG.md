# Changelog

## Unreleased — Math application trial

- Separate `codex/math-app` branch for Mac user testing; no installer or released-main changes.
- Three passive, tap-to-reveal number/arithmetic modes through 100, weighted per number and grouped into tens.
- Standard launcher: Paint/Photos/Music above Typing/Reading/Math; existing custom configuration is preserved.
- Pictures-first Numbers and on-demand offline speech for 0–100; no autoplay, scoring, learning history or object-tapping controls.

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
