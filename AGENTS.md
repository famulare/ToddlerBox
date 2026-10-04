# Repository Guidelines

## Project Structure & Module Organization
- `src/toddlerbox/` contains the launcher and apps (`paint/`, `photos/`, `typing/`, `music/`, `reading/`, `math/`).
- `src/toddlerbox/ui/` contains shared UI helpers and widgets.
- `src/toddlerbox/runtime/` contains runtime safety/logging helpers.
- `tests/` holds pytest unit tests.
- `assets/` is reserved for launcher icons and other static files.
- `config.yaml` provides dev defaults (paths, palette, app commands).
- `toddlerbox_design_contract.md` is the source of truth for product requirements.

## Build, Test, and Development Commands
Use `uv` with the local `.venv`; the repo scripts now pick a per-user writable cache automatically.
- `uv venv .venv` — create or refresh the virtualenv.
- `uv sync --frozen --group dev` — install in editable mode with test deps.
- `uv run python -m toddlerbox.launcher` — run launcher.
- `uv run python -m toddlerbox.paint` — run paint.
- `uv run python -m toddlerbox.photos` — run photos.
- `uv run python -m toddlerbox.typing` — run typing.
- `uv run python -m toddlerbox.music` — run music.
- `uv run python -m toddlerbox.reading` — run reading.
- `uv run python -m toddlerbox.math` — run the application-only Math trial.
- `uv run --frozen pytest` — run unit tests.
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

## Product principles and change boundaries

- Build an understandable appliance for a child, not a general-purpose kids product. The design contract is authoritative. Do not add scores, rewards, accounts, tutorials, analytics, advertisements, dialogs, or automatic progression without an explicit request.
- Each activity has one clear purpose. Reuse the shared theme, Home placement and original illustrated icon language. Avoid decorative chrome, competing controls and unnecessary settings. Parent administration belongs in authenticated parent mode.
- The bootable Ubuntu image is the primary target. App-only desktop tests cannot establish session containment, gestures, boot recovery, audio routing or hardware compatibility. Never run Cage inside GNOME as the production child session.
- Parent escape and health supervision must remain independent of the launcher. Long transfers or maintenance must not block recovery. Retry bounds, recovery states and failure evidence must be explicit.
- Preserve child work first. Use durable atomic writes, stable upload snapshots and conservative imports. No automatic archive/history pruning, deletion propagation, or rollback of child data. Test disk-full, interrupted writes and save/transfer races when changing persistence.
- Keep child use offline. Drive sync and OS/app maintenance are parent initiated; do not add timers, watchers, network-triggered jobs or background installation.
- Child data, credentials, device identity and setup progress live outside versioned app releases. Credentials stay root-owned/private. Never place real family media, OAuth tokens, signing keys or private setup packages in source, images, screenshots, diagnostics or public artifacts. Use synthetic fixtures on builders.
- Use authenticated bounded IPC with process-identity checks. Do not weaken Linux credential, pidfd, path, symlink or permission guards to make tests pass on another OS.
- Signed public GitHub release metadata and fixed update paths are the update trust boundary. No Git login is required on the appliance. Preserve the resident boot gate and known-good system/app pair; candidate acceptance requires a real supervised child test and explicit parent confirmation.
- Read affected code and record the actual baseline. Compare genuine old/new code under identical inputs; deterministic unaffected frames and saved files must match exactly. Add focused failure tests and run the relevant suite through uv. Reproduce claimed pre-existing failures on the unchanged baseline.
- Obtain independent review at useful module/recovery boundaries when requested. Resolve findings before qualifying the final image. Preserve previously qualified disks and checkpoints; use disposable VM targets.
- Release only the exact source identity that was built and qualified. Record commands, toolchain, package manifest, checksums and remaining limits in VALIDATION.md. Verify published artifacts; do not call VM evidence physical hardware validation.
- Update README, contract, current setup/update/build guides and changelog together. Retire obsolete operational instructions rather than leaving competing startup paths. Keep provenance/license records; label historical research as historical.
- Do not ask a parent to manually authenticate hashes for normal signed updates. Destructive installation still requires human confirmation of the exact physical disk and a private verified backup.
- Keep work scoped and resource conscious: reuse evidence when inputs are unchanged, avoid broad review campaigns, and do not promise a measured account quota.
- The Math trial stays on `codex/math-app` until Mac user testing and explicit integration approval. Do not merge it, rebuild an installer or publish a release as part of the application trial. Keep the standard launcher two rows of three: Paint/Photos/Music, then Typing/Reading/Math. Math objects are passive; answers reveal on tap with no assessment.
