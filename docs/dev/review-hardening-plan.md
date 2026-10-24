# Dev branch plan: review hardening (`dev/review-hardening`)

Dev-only working plan. It is not a release document and is not intended for `main` as-is.

- **Base:** `origin/main` `b3d87f9` (0.5.1).
- **Status:** agreed between Claude (implementer) and Codex `gpt-6-astra` (reviewer),
  2026-10-23, after three review rounds.
- **Progress (2026-10-23):** WP12, WP1, WP2, WP5, WP7, WP3, WP4, WP10, WP6, WP11, WP8 and
  WP9 are implemented and committed with tests, plus fixes for Codex implementation
  review 1. Remaining: Linux CI and VM runs (need the branch pushed), the signed update
  chain in a VM, and physical HP acceptance.

Constraints are inherited from `AGENTS.md`:
- Preserve child work first.
- No pruning, deletion propagation or rollback of child data.
- No background network jobs.
- No new child-facing UI.
- Compare old and new code on identical inputs.
- Run tests through uv.
- Update the contract, guides, changelog and `VALIDATION.md` together.

## 1. Confirmed defects on 0.5.1

| ID | Defect | Evidence on b3d87f9 |
|---|---|---|
| H1 | `_save_surface_atomic` (`paint/app.py:132`) uses `pygame.image.save`, which returns normally after a short write. It is still used by the synchronous final save at shutdown/TERM (`:945`) and by `_archive_current` (`:1068`) | RLIMIT_FSIZE probe: a 164 KB `latest.png` became an undecodable 54 KB file |
| H2 | New and Recall archive blank or unchanged documents | 105 New taps gave 100 identical archives, then New and Recall are inert (Typing: 200) |
| H3 | Sync: one bad Drive photo aborts the run before creations upload (`worker.py:241`) | Corrupt PNG raises an uncaught `SyntaxError`; case duplicates and one failed download each upload 0 creations |
| H4 | `load_config()` and icon loading raise on malformed YAML or icons, so the child session never starts | `config.py:121`, `launcher.py` |
| H5 | A persistent save failure cancels exit in Paint and Typing | Probe: Paint Home stays; Typing keeps running |
| H5b | Restore crash-loops (unguarded quarantine rename; Typing `KeyError`/`RecursionError`) | Probe |
| H6 | The boot gate validates accepted journals (`boot_recovery.py:186`). The updater writes markers before validating (`update_bundle.py:248`) | 0.4 probes; code unchanged |
| M6 | Typing zero-advance code points make rendering raise | Probe |
| M9 | Reading catalog misses Pillow `SyntaxError` (`catalog.py:171`) | Read |
| M12 | Sync staging is never swept; worker deadline equals the unit timeout | Probe: staged child work left after SIGTERM |

Existing update and rollback VM coverage (`scripts/qualify-patch-update.py`) is retained and extended.

## 2. Delivery mapping

The resident restore table (`boot_recovery.DESTINATIONS`) and the updater table
(`update_bundle.FILES`) list 11 files. This branch does **not** change either table.

| Class | Reaches existing appliances by | Contents |
|---|---|---|
| **A. App release** | Signed app update | WP1, WP2, WP3, WP4 (app side), WP5 (Reading/Paint), WP7 |
| **B. Updatable root tools** (in `FILES`) | Signed bundle | `toddlerbox-session` (WP4 `TODDLERBOX_DATA_ROOT`); `toddlerbox-maintenance` (WP2 counts, WP10); `update_bundle.py`, `toddlerbox-install-release` and the `toddlerbox-update` bootstrap (WP10, WP11); `appliance.py` |
| **C. Fresh image only** | A new installer (no migration in this branch) | `tbx_sync/*` and its `image_safety` copy (WP5 sync side, WP6); `boot_recovery.py` (WP8); firstboot, sysctl, GRUB (WP9) |

Moving C to existing appliances needs a separately designed and qualified resident
migration. It is out of scope here.

## 3. Work packages, in agreed order

### WP12. Tooling first
- `.python-version` set to 3.12.
- Reproduce each macOS failure, then mark only the proven Linux-only tests
  `skipif(sys.platform != "linux")`.
- `ci.yml` on push and PR (`dev/**`, `main`), run through uv:
  - pytest on ubuntu-24.04 with `/usr/bin/python3`
  - an `ubuntu:24.04` container job running the sync tests against apt `python3-pil`,
    asserting at runtime that `PIL.__file__` is the apt copy
- Narrow `ruff check` rule set; no mass reformat.

### WP1. Durable save path
- **Bytes-only commits.** Encoding to bytes happens off the UI thread. `write_bytes`
  keeps `CommitUncertainError`. Paint encodes with PIL (pixel-identical to the old output;
  bytes may differ) and never calls `pygame.image.save`.
- **Fixed per-target temp names, with orphan recovery.** Before any write to a target, the
  owning store checks for that target's orphan temp.
  - If it validates (PNG decodes within limits, or Typing JSON validates), publish it
    no-clobber as a Recall archive named `recovered-<ns>`. This is exempt from capacity,
    which is nondestructive anyway.
  - Otherwise rename it to `corrupt-<ns>`.
  - Only then is the temp path reused. Temps are never deleted, and they are excluded from
    archive globs and Recall.
- **Restore never raises.**
  - Parsing is bounded, and the quarantine rename is guarded.
  - If quarantine fails, start blank and disable writes to `latest`/`current` for the
    session. This restriction travels with parked work, so the unreadable original is
    never overwritten.

### WP2. Archive deduplication
- **Content hash.** Hash document content only, excluding timestamps and cursor
  bookkeeping.
- **When to skip.** Skip archiving a blank document. Skip one whose hash matches a durable
  archive that still exists (the newest, or the recalled source).
- **Capacity.** Deduplication is checked before the capacity refusal. Existing archives are
  never touched.
- **Parent signal.** `toddlerbox-maintenance` status shows archive counts and capacity:
  counts only, no names.

### WP5. One image-decode error contract
`DECODE_ERRORS` (including `SyntaxError`, `EOFError` and the bomb errors) lives in
`runtime/image_safety.py` and is used by:
- Reading's catalog
- Paint's PIL paths
- the sync `validate_photo` (normalised to `ValueError`)
- package import

Pixel limits and strict decoding are unchanged. It is tested under both the app's Pillow
and apt Pillow.

### WP7. Typing input bounds
- New input is capped at 20,000 glyphs and 2,000 lines. Glyph sizes are bounded.
  Existing oversized documents are never truncated.
- Only single, printable code points are accepted.
- Rendering skips unrenderable or zero-advance glyphs without deleting them from the document.
- The loader preserves the original under quarantine first, then salvages the validated
  glyphs. Unparseable structure stays quarantined.
- No same-key repeat limiter, pending keyboard testing.

### WP3. Exit is never blocked
- **Parking.** Each activity has one `ParkedWork(revision, payload, writer, write_disabled)`
  slot in the launcher.
  - Home and exit never wait on storage.
  - A failed or in-flight save parks the work.
  - A reopened activity adopts its slot and polls any in-flight writer before issuing its
    own, so each target has one writer for the launcher's lifetime.
- **Save-current.** `runtime/control` gains a registry of retained work. `save-current`
  replies `ok` only when the active callback and every parked saver return True. It
  reports `SAVE_PENDING` while any is pending and `failed` otherwise, in every activity and
  on Home. It never blocks the frame loop.
  - Retention in RAM is never reported as durable.
- **Esc.** Esc no longer exits Paint, Typing or Photos when `TODDLERBOX_APP_CONTROL=1`.
  Desktop development keeps Esc.
- **Contract.** The contract and tests are updated.

### WP4. Config and launcher resilience
- **Loading never raises.** A parse failure, non-dict YAML or a missing env-named file
  means log and use defaults. There is no CWD fallback when `KIDBOX_CONFIG` is set.
- **Storage root.** `TODDLERBOX_DATA_ROOT`, set by `toddlerbox-session`, pins the appliance
  storage root, the same root sync uses.
- **Validation.**
  - Nested structures, palette colours, finite numbers and launcher commands are validated.
  - Invalid app entries are dropped; if none are valid, the standard six are used.
  - A failed icon load gets a fallback tile.
  - Defaults are deep-copied.
- **Global state.** The launcher resets global SDL state (clip, key repeat) in a `finally`
  after each embedded app.
- **Check command.** `/opt/toddlerbox/current/.venv/bin/python -m toddlerbox.config --check FILE`
  validates a file, and `docs/updates.md` tells parents to run it.

### WP10. Parent-facing refusal messages
- Each tool keeps its own fixed error codes and messages (no shared app-environment module).
- Unexpected exceptions stay generic.
- Fix the misleading "rollback first" text shown while a candidate is pending.

### WP6. Sync isolation and cleanup (class C)
- **Phase order and budgets.** The order is initial backup → creations → photos. Each
  phase has its own error boundary and byte budget, under an aggregate ceiling.
  - Initial backup may use at most 50% of the run deadline.
  - Global failures (authorization, offline, timed out) stop the later phases.
  - Item failures become issues and the run continues.
- **Initial backup resumability.** `initial.json` gains durable per-item progress
  (name → sha256) tied to `package_id`, and verified items are skipped.
  - A phase deadline (`TransferError('phase-deadline')`) interrupts in-flight rclone and is
    reported as `initial-backup-incomplete`.
  - Tests prove eventual completion across bounded runs.
- **Photos.** Per-item transfer and decode failures become issues. Case-duplicate names
  skip only those names.
- **Creations manifest.** `manifest.json` is withheld whenever any snapshot or creation
  upload or verification fails. A complete manifest lists every verified file, including
  unchanged ones. Tests show an older manifest then refuses restore of changed files rather
  than restoring a mix.
- **SIGTERM.** The handler records `interrupted`, then exits via `SystemExit`.
- **Staging sweep.** `staging/*` is swept at job start, under the lock (for SIGKILL).
- **Deadline.** The internal deadline is the unit timeout minus 60 s.
- **Filenames.** Bounded filename lists go only into the root-only `status.json`, never
  into the shareable maintenance report.

### WP11. Update path guards (class B)
- **Unsigned paths.** On `appliance-v1`, unsigned direct installs and alternate rollback
  entry points (the `toddlerbox-update BUNDLE SHA` bootstrap, direct
  `toddlerbox-install-release`, `toddlerbox-mode rollback`) require an explicit
  `--unsigned-recovery` flag and respect the maintenance marker and any pending journal.
- **Install publication.** Fsync extracted files and directories before publishing.
- **Conflicting release directory.** If one is not referenced by current, previous or any
  journal, preserve it under a non-colliding name and re-extract. Never prune.

### WP8 and WP9. Resident and image (class C, qualified separately)
- **WP8.**
  - Only *missing historical rollback material after acceptance* becomes advisory
    (`rollback-unavailable`). Malformed, unsafe or integrity failures still fail closed.
  - The updater validates before writing markers.
- **WP9.**
  - `kernel.sysrq=16`.
  - `GRUB_RECORDFAIL_TIMEOUT=5`.
  - firstboot retries `passwd` up to 3 times, then exits with "reboot to try again".
  - Clock-sanity refusal: a clock earlier than the build's release date gets parent
    instructions in maintenance and sync.
  - The GRUB menu, GRUB authentication and the time service are unchanged in this branch.

### Deferred
- Update redesign and the resident candidate lifecycle (M16).
- Transient units (M17), the installer disk guard (M19), and the controller refactor (M11).
- Photos index (M8), the audio service (M10), and release-config consolidation (M23).
- Parent-side operations (a dedicated Google account, consolidating the private kit) are
  tracked privately.

## 4. Testing tiers

1. **Local (Claude, Mac via uv).** Real fault injection: RLIMIT_FSIZE, read-only
   directories, short writes, fake Drive, SIGTERM/SIGKILL. Old and new code compared on
   identical inputs.
2. **Linux CI.** `ci.yml`, as in WP12.
3. **VM.** See `docs/dev/vm-and-hardware-work-plan.md`.
4. **Physical HP acceptance.** The owner.

VM evidence is never described as hardware validation. The exact final candidate is
qualified separately from dev evidence.
