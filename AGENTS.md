# Repository Guidelines

## Project Structure & Module Organization
- `src/toddlerbox/` contains the launcher and apps (`paint/`, `photos/`, `typing/`, `music/`, `reading/`).
- `src/toddlerbox/ui/` contains shared UI helpers and widgets.
- `src/toddlerbox/runtime/` contains runtime safety/logging helpers.
- `tests/` holds pytest unit tests.
- `assets/` is reserved for launcher icons and other static files.
- `config.yaml` provides dev defaults (paths, palette, app commands).
- `toddlerbox_design_contract.md` is the source of truth for product requirements.

## Build, Test, and Development Commands
Use `uv` with the local `.venv`; the repo scripts now pick a per-user writable cache automatically.
- `uv venv .venv` — create or refresh the virtualenv.
- `uv pip install -e ".[dev]"` — install in editable mode with test deps.
- `uv run python -m toddlerbox.launcher` — run launcher.
- `uv run python -m toddlerbox.paint` — run paint.
- `uv run python -m toddlerbox.photos` — run photos.
- `uv run python -m toddlerbox.typing` — run typing.
- `uv run python -m toddlerbox.music` — run music.
- `uv run python -m toddlerbox.reading` — run reading.
- `uv run pytest` — run unit tests.
- `./scripts/run-stable.sh` — bounded process-exit retries for development.
- `./system/build.sh` — build the Ubuntu VM disk and USB installer from the shared system recipe.
- `./system/vm.sh start` — boot a disposable overlay with QEMU; see `system/README.md` for recovery and qualification.

## Coding Style & Naming Conventions
- Python: 4-space indentation; keep modules small and focused.
- File names: lowercase with underscores for Python modules (e.g., `photos/app.py`).
- Config: YAML keys in lower snake_case.

## Testing Guidelines
- Framework: `pytest`.
- Prefer unit tests for pure logic (config merge, file naming, thumbnail cache decisions).
- Name tests with behavior-focused descriptions (e.g., `test_autosave_atomic_write`).

## Commit & Pull Request Guidelines
- Use short, imperative commit messages (e.g., “Add paint app autosave”).
- PRs should describe changes, reference the design contract section, and include screenshots for UI changes.

## Security & Configuration Tips
- Do not commit secrets or local env files (`.venv/`, `.env`).
- Dev config uses `config.yaml` at repo root; the system image sets `KIDBOX_CONFIG=/etc/toddlerbox/config.yaml`.
- Production dependencies are installed with uv at build time; runtime executes the versioned environment directly and remains offline.
- Data writes default to `data_root` from config; dev defaults to `./data`.
- Runtime logs are written under `data_root/logs/` (`toddlerbox.log` with `.1` rollover).

## Agent-Specific Instructions
- Keep UI minimal and fullscreen; avoid dialogs and OS UI elements.
- Prioritize autosave safety and graceful failure (no error UI for child-facing screens).
