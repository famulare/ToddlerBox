> Historical review of an earlier source checkpoint. Targeted repairs have landed; use the current design contract and VALIDATION.md for present behavior. Findings below retain their original evidence and are not a current open-issue list.

# Independent ToddlerBox design review

Reviewed **3b2917941187627360371447447dcfd465ba4457**, branch `system/bootable-ubuntu`, on 2026-10-02. This review covers the application and its recovery boundary. It makes no application or system changes. Music is discussed only as a proposed extension.

**Implementation update:** the user subsequently authorized targeted repairs. The findings below describe the reviewed baseline; the resolution record at the end describes the resulting implementation and remaining qualification work.

## Verdict

**I would keep Python, pygame, a single application window, embedded activities, and the dedicated Cage child session. I would not rewrite ToddlerBox.** Those choices fit a small, offline appliance with deliberately simple screens. The independent root controller and ordinary authenticated parent desktop are a much better separation of responsibilities than asking a fullscreen application to suppress a desktop shell's gestures.

I would change several implementation details before treating this as an everyday child appliance. Input handling currently has reproducible correctness defects, Paint's autosave can be starved by ignored keys, and unbounded synchronous work can make an otherwise healthy activity appear hung. Fixing these calls for a small shared input/lifecycle layer, better work scheduling, and targeted regressions—not another GUI framework or a general plugin system.

This is **not a diagnosis of the HP's previous instability**. I did not access that machine, reproduce its GNOME gesture escape, or repeat the documented VM qualification. Cage removes GNOME shell gestures from the child-session architecture; that does not establish touchscreen mapping, graphics stability, or recovery timing on the HP.

## Evidence and scope

- Read `AGENTS.md`, the application/system contract, application implementations, persistence and health helpers, controller/service/session configuration, release installation/rollback, relevant tests, and `VALIDATION.md`.
- Independently ran `UV_CACHE_DIR=/workspace/.cache/uv uv run --offline pytest -q`: **65 passed in 0.95 seconds** at the reviewed baseline.
- Ran additional one-off checks through `uv run --offline python` with SDL dummy video/audio, temporary data directories, actual pygame surfaces, and selected event/clock mocks. Results below labeled **reproduced** came from those checks, not speculation. They are application-level reproductions, not physical touch tests.
- Did not build another image, modify runtime code, run power-cut/full-guest disk tests, or perform a soak. Previously documented VM results are useful evidence with their stated limits, not a substitute for these missing tests.

Severity: **P1** should precede everyday use because it affects core interaction or saved-work guarantees; **P2** is a concrete correctness or reliability improvement; **P3** is a smaller usability/maintenance issue. No confirmed application-to-parent security escape was found in this review.

## Findings, in priority order

### 1. P1 — Ignored keyboard activity can indefinitely postpone Paint autosave

**Reproduced.** `PaintApp._handle_resume()` assigns `last_autosave = time.monotonic()` at `src/toddlerbox/paint/app.py:433`. `_should_reset_for_key()` classifies function keys and modifier shortcuts as input-reset events (`:450–459`), and the event loop calls that reset for every such key (`:1040–1042`). The periodic save compares against the reset timestamp (`:1071–1074`).

A mocked-clock run delivering F1 once per second for **30 seconds produced zero periodic saves**, with the normal ten-second interval. Continuing this pattern can postpone saving indefinitely. This matters for a toddler who draws while also repeatedly pressing keys: the documented ten-second recovery window no longer holds. Home/normal termination still attempt a save; sudden interruption does not.

**Change:** keep pointer/focus reset independent of save scheduling. Track the last successful commit and document dirty state separately. A focus event, long frame, or ignored key must not move an outstanding save deadline forward. Add an event-loop regression with repeated noisy keys and a dirty canvas.

### 2. P1 — Pointer handling does not provide one coherent touch stream

**Reproduced in synthetic SDL events; manifestation on the HP remains unverified.** There are two separate concrete bugs:

- `src/toddlerbox/ui/common.py:18–20,161–169` recognizes normalized positions for FINGERDOWN/FINGERUP only. For a FINGERMOTION event without `.pos`, `pointer_event_pos()` returns `None`. Paint calls it before checking the finger-motion type (`paint/app.py:607–619`), so pure finger-motion drawing is dropped (`:1057–1066`). A synthetic event with `x=.5, y=.5` returned `None` from both helpers. Photos and recall overlays contain their own manual motion conversion, demonstrating inconsistent handling across activities. If SDL also emits synthetic mouse motion, that can mask the Paint bug.
- Normal Paint and Typing controls accept both finger-down and touch-emulated mouse-down without deduplication (`paint/app.py:1050–1055`; `typing/app.py:1183–1196`). Starting with Typing text `abc`, one finger-down plus its emulated left-mouse-down on Undo produced **`a`**, not `ab`. Photos and recall have a boolean duplicate guard, but no app tracks an owning finger ID. A second finger's motion/up can therefore steer or end the first finger's gesture.

**Change:** normalize mouse/touch at one boundary. Choose an explicit policy for SDL's emulated mouse events, include finger motion, track the active device/finger, and define how secondary contacts are ignored. Emit one press/move/release/cancel stream to all activities. Keep keyboard/trackpad input usable. Test raw finger-only sequences, finger plus synthetic mouse sequences, two fingers, focus loss, and down/up spanning scene changes. Then confirm the actual SDL event stream on the HP.

### 3. P2 — Paint bucket fill overwrites an unrelated pixel

**Reproduced.** The slice-support probe in `_bucket_fill()` writes pixel `(0, y)` and then restores it to the clicked region's target color, rather than that pixel's original color (`src/toddlerbox/paint/app.py:254–259`). This can erase a boundary and change flood-fill connectivity.

Minimal reproduction: create a 5×3 white surface, set `(0,1)` black, then fill from `(3,1)` with red. The black pixel becomes red. It is outside the original white region and should remain black.

**Change:** remove the destructive capability probe, probe a disposable surface, or preserve the exact original pixel. Add a small reference-image test covering disconnected regions and boundaries.

### 4. P2 — A Paint tap produces no mark

**Reproduced.** `_handle_pointer_down()` records a stroke and undo surface (`src/toddlerbox/paint/app.py:706–712`); actual marking starts only in `_handle_pointer_move()` (`:746–781`). `_handle_pointer_up()` simply discards the stroke (`:783–784`). A down/up at the same canvas point leaves the surface byte-for-byte unchanged.

This is a basic touchscreen expectation and also wastes an undo entry. It affects brush/pen dots and eraser taps.

**Change:** stamp the initial point once on down, with the correct current tool width/color, and retain continuous stroke behavior. Verify tap, short stroke, and Undo for each drawing tool.

### 5. P2 — Normal content growth can monopolize the frame loop

**Observed design exposure, with a measured Typing example; watchdog failure on the HP was not reproduced.** The supervision design treats a 20-second frame gap as a hung application (`system/controller.py:40–59`). Several normal operations have no bounded amount of work:

- Launcher constructs Photos before drawing its first launcher frame (`src/toddlerbox/launcher.py:203–218`). Photos scans every file for EXIF, loads initial thumbnails and a full image synchronously (`photos/app.py:138–164,246–261`). Later thumbnail “time budgets” are checked only **after** a complete decode/scale/save (`:631–638`); one expensive image can exceed the entire budget. Every loaded thumbnail remains in `PhotoItem.thumb` for the process lifetime, including while other activities run.
- Paint recall decodes/scales every archive synchronously (`paint/app.py:847–869`). Bucket fill, PNG encoding/fsync, and thumbnail work also execute on the UI thread. Paint rewrites unchanged `latest.png` every ten seconds.
- Typing recomputes widths and wrapping for the entire document every frame (`typing/app.py:725–762,1081`) and renders glyph surfaces repeatedly. In this workspace, `_render()` took approximately **24 ms for 10,000 characters and 105 ms for 100,000 characters**. These are single-run headless measurements, not HP benchmarks, but show the scaling problem. The document has no length bound, and key repeat is 30 ms (`:354`). Typing recall parses all archives before retaining at most 200 (`:183–222`); that limit bounds results, not I/O or total storage.

**Change:** first cache Typing layout until text/style/width changes and avoid saving unchanged Paint canvases. Bound the in-memory thumbnail cache; load visible items first; prepare photo metadata/size-limited derivatives outside the interactive path. Move slow decoding/encoding to a controlled worker where needed, with immutable snapshots, bounded queues, and pygame display work confined to the UI thread. Do not add a timer that feeds the watchdog while the UI is stuck: that defeats the watchdog's purpose. Measure real frame/save latency on representative HP content before tuning timeouts.

### 6. P2 — The generic subprocess fallback conflicts with system supervision

**Confirmed by code path; no new full-guest reproduction.** `_launch_app()` performs `child.wait()` at `src/toddlerbox/launcher.py:144–150`. During an arbitrary external program, the launcher neither processes events nor reports completed frames. Unless the child implements the health protocol itself, the controller's 20-second timeout will restart the graphical session. Suppressing stdout/stderr does not provide this missing lifecycle integration.

The three current activities avoid this because they are embedded. The fallback advertised by the contract is therefore not a generally usable production extension point.

**Change:** keep production activities embedded for now, and reject or clearly restrict unsupported external commands in parent configuration. If external programs eventually become necessary, specify their health, exit, shutdown, and compositor/window ownership contract explicitly. Music should not use this fallback.

### 7. P2 — Archive retention has saved-work edge cases and lacks a consistent policy

**Reproduced for zero retention; other consequences follow directly from the code.** `_coerce_archive_limit()` accepts zero (`src/toddlerbox/paint/app.py:147–152`). `_archive_current()` saves, enforces retention, then reports success (`:810–824`). With `max_archives: 0`, pressing New deletes the archive just created, clears the canvas, and overwrites `latest.png`. A red canvas reproduced this with only a white `latest.png` remaining.

With the default limit of 100, old Paint work is silently deleted. Also, preservation files named `corrupt-*.png` are included by `_list_archives()` and count toward ordinary retention (`:124–127,385–387,826–839`), so “preserved for parent inspection” is not permanent. Typing has the opposite policy: archives grow without a storage bound.

**Change:** disallow zero when successful archiving is the prerequisite for clearing; exclude quarantined corruption files from automatic artwork retention. Establish an explicit parent-visible retention/export policy and disk reserve. Distinguish discardable caches from child-created work. Avoid new child dialogs; expose capacity/save failures in parent diagnostics. Test the retention boundary and New/Recall failure paths together.

### 8. P2 — Atomic replacement is sound, but the stated failure guarantee is too broad

**Reproduced with an injected directory-fsync failure.** `runtime/persistence.py:21–25` correctly fsyncs the temporary file, replaces the destination, then fsyncs the directory. If that **last** operation fails, the new destination is already visible even though the caller reports failure. Injecting failure only into `sync_directory()` left `b'next'` at a path previously containing `b'previous'`.

This does not show a torn PNG/JSON file or prove loss during a power cut. It shows that “failed saves preserve the previous committed file” is only assured for failures before replacement. Existing `test_failed_flush_preserves_previous_file` fails the first file fsync, so it does not exercise this distinction (`tests/test_durable_work.py`).

**Change:** document pre-commit failure versus uncertain durability after replacement, and add the missing boundary test. If preservation of an independently recoverable prior revision is a product requirement, use a separate previous-generation save with a deliberate commit/recovery protocol. Do not try to blindly undo a rename after directory-fsync failure. Retain the current fsync design; the problem is the claimed guarantee and untested boundary.

### 9. P2/P3 — A few ordinary display/content cases remain incorrect

**Reproduced headlessly.** These are smaller than the input and save issues but should be covered by representative fixtures:

- **P2 on low-resolution displays:** with the shipped 14-color palette at 1024×600, palette entries 11–13 overlap Paint's Recall rectangle. Minimum swatch height overrides available height (`paint/app.py:583–603`), and palette hit testing precedes Recall (`:725–742`). At 1366×768 this check found no overlap. The HP's actual display mode is unknown. Reflow or scroll the palette and assert non-overlapping controls at supported sizes.
- **P2 for photo usability:** EXIF orientation is not applied by the pygame loader (`photos/app.py:92–99`). A 40×20 JPEG with orientation tag 6 remained 40×20; upright display should be 20×40. Apply orientation consistently to the main image and thumbnail; use phone-photo fixtures.
- **P3:** the cached Photos instance does not rescan its library on relaunch (`photos/app.py:311–323`). Adding a PNG after constructing an empty library and relaunching still produced zero items. Parent-mode transitions currently restart the app, so the usual production import path may mask this. Either document refresh-on-session-restart or add an inexpensive library-change check.

## System boundary: what is sound, and what still needs proof

The system direction is appropriate. `system/bin/toddlerbox-session:5–16` runs native Wayland under Cage without a child GNOME shell, with session-scoped power/lid inhibitors and an explicitly selected software renderer. Separate accounts, root-owned releases/configuration, root-only control commands, peer credentials on the sockets, and an input reader outside pygame give recovery a meaningful boundary (`system/configure-rootfs.sh:21–27,58–78`; `system/controller.py:110–125,193–244`). The code does not pretend that checking pygame modifiers can prevent compositor gestures.

Keep the frame-derived heartbeat, non-resetting restart budget, persistent parent latch, independent console route, and versioned releases. Their limited failure domains are more valuable than having every app recover from every possible exception. Keep the documentation's distinction between app rollback and OS/image reinstall, and its explicit warning to preserve data before reinstalling.

I would nevertheless require these system checks before everyday use:

1. **P1 qualification gap — controller failure, not just app failure.** Kill and SIGSTOP the controller under systemd, including during a mode transition, and verify actual GDM state, parent authentication, persistent recovery state, and a subsequent reboot. The unit has systemd watchdog/restart/OnFailure behavior; the controller also uses a runtime marker to select parent mode on restart (`system/units/toddlerbox-controller.service`; `system/units/toddlerbox-recovery.service`; `system/controller.py:145–167`). Main startup writes the new mode but does not itself call `restart_gdm()`, so recovery relies on the complete systemd/GDM sequence. The four controller unit tests exercise only `Watchdog`/`EscapeChord`, not that sequence. This is a missing proof, not a claimed reproduced recovery failure.
2. **P1 qualification gap — physical device and storage failures.** Repeat the documented child/parent tests on the HP with raw event capture available; include all screen edges, two fingers, touch and trackpad alternation, keyboard disconnect/reconnect, cold boots, and parent sleep/resume. Separately test full-guest ENOSPC and abrupt power cuts during current-save/archive commits. The temporary GDM config helps disk-full recovery, but cannot establish that a full root filesystem permits GNOME login or durable recovery-latch creation. The controller explicitly logs latch-write failure and proceeds (`controller.py:172–180`).
3. **P2 design risk — shutdown uses a fixed two-second grace period.** `restart_gdm()` sends TERM by exact process argv, waits two seconds, sends KILL, then restarts GDM (`controller.py:96–107`). It has no save-complete acknowledgement. Two seconds may suffice for the demonstrated short documents, but not a large canvas or slow/failing flash storage. Measure this on the target and consider a bounded explicit shutdown acknowledgement plus reliable process/session identity. Parent escape must remain available even if saving cannot complete.
4. **P2 design risk — rollback durability and compatibility.** Installation calls `os.sync()` around switching releases (`system/bin/toddlerbox-install-release:50–58`), but controller rollback replaces `current`/`previous` without a directory fsync (`controller.py:128–138`). A power cut between two symlink replacements also has a different outcome from a completed swap. Qualify interrupted release switching, preserve an identifiable known-good release, and specify data-schema compatibility. Typing currently treats an unsupported save version as corrupt (`typing/app.py:556–575`); a future rollback must not quietly turn valid newer work into an empty working document. No failed-power-cut outcome is claimed here.

## What I would keep in the application

- The restrained fullscreen interface, large activity choices, consistent Home affordance, no dialogs or diagnostic traces in child-facing screens, and ordinary parent tools outside child mode.
- One pygame display with embedded activities. It minimizes focus/window handoff, permits shared input normalization, and is adequate for four small offline activities. Independent system recovery covers a whole-process hang.
- The separation between mutable data and immutable application releases, current-document restoration, archiving before New/Recall replacement, atomic file replacement, and best-effort bounded application logs.
- Paint's bounded undo snapshots and Typing's small edit-operation undo history. Their complexity is proportionate to the product; neither needs a general document framework.
- Tests for persistence failures, rich wrapping, resume-state reset, restart budgets, and the independent chord. Expand them around demonstrated behavior; a passing count alone is not a qualification measure.

## Maintainability changes I would make incrementally

The main issue is repeated lifecycle/input policy scattered through three sizable app files, not Python itself. Paint is about 1,100 lines and Typing about 1,240. The duplication already differs in finger motion, duplicate suppression, focus events, global keyboard-repeat state, and save-on-exit behavior.

Extract a small common activity host with explicit enter/exit/cancel-input/shutdown behavior and one normalized input stream. Keep app-specific drawing, document state, and persistence code separate and directly testable. An interface such as `enter`, `handle_event`, `update`, `render`, `leave` is enough; do not build a plugin platform. Migrate one activity at a time after input regression fixtures exist. Keeping the current runner functions during the transition is reasonable.

Centralize configuration validation and app registration. Reject invalid timer values, impossible layout/data limits, missing mandatory assets, and unsupported production commands before a child session begins; retain useful parent logs. Avoid heuristic coordinate selection based on which button might be hit (`paint/app.py:656–672`) as the long-term mapping policy. Establish actual SDL window/surface coordinates for the target and apply one deterministic conversion to every activity.

Treat caches, archives, and current documents as different data classes with different bounds. Keep the smallest viable amount of parent-only status: last successful save, pending/failed saves, content size, frame latency, current release, and restart reason. This supports troubleshooting without violating the child UI contract.

## Implications for the proposed offline Music activity

Music fits the existing architecture and does not justify a rewrite. Add it as another embedded activity with a Home control and simple track choices/autoplay; keep audio and falling-note animation out of external-player subprocess fallback. Confirm launcher layout with four icons at supported screen sizes.

Design one score/event representation containing note pitch, start time, duration, and piece identity. Use that as the source for both generated/prepared audio and the visualization, with one playback clock and an explicit offset/latency model. A render loop that independently counts frames or sleeps until each note will drift and obstruct Home/watchdog processing. Pre-render short pieces or prepare bounded audio data away from the interactive loop; draw visible notes from playback position.

Specify behavior for audio-device absence/loss, track changes, Home, SIGTERM, and exceptions. Returning Home or parent recovery must stop audio and release activity-owned resources even when the mixer remains initialized process-wide. Audio failure should produce a quiet child-facing state and parent diagnostics. Add tests for timeline/seek/track transitions and cleanup, then verify audiovisual synchronization on actual hardware. Composition public-domain status and arrangement/recording licenses require separate source review.

## Recommended order

1. Fix autosave starvation, unify pointer semantics, fix bucket fill and tap marks; add focused event-sequence/image regressions.
2. Make retention safe, cache Typing layout, bound photo work/cache growth, and correct EXIF/layout cases. Add parent-only save/latency diagnostics and clarify post-rename durability semantics.
3. Complete controller-failure, disk-full/power-cut, and representative-content soak qualification. Then qualify the HP; do not infer its behavior from virtual input.
4. Extend the embedded model to Music after its score, source/license, playback-clock, and audio-cleanup design is agreed. Evolve the shared lifecycle while doing so; keep the proven system boundary.

The existing direction is worth strengthening. The concrete problems are local and testable; replacing the stack would discard useful work while leaving input, persistence, and hardware qualification responsibilities unchanged.

## Authorized repair resolution — 2026-10-02

The application/system stack is retained. Repairs were implemented with focused regression and failure-injection coverage; no physical HP or power-cut result is implied.

| Finding | Implemented repair |
| --- | --- |
| 1: autosave starvation | Input resets no longer change Paint's save deadline. Repeated ignored keys still permit periodic saves. |
| 2: touch streams | Shared `PointerInput` owns one mouse/finger gesture, rejects secondary contacts and SDL touch-emulated mouse duplicates, and resets on activity/focus changes. Finger-motion coordinates now work. Reset handlers discard already-fetched stale input while preserving QUIT. |
| 3: bucket corruption | Removed the destructive PixelArray capability probe; boundary pixels are preserved. |
| 4: tap marks | Brush/pen/eraser stamp on pointer-down; a tap is one undoable operation. |
| 5: frame-loop work | Photos scans/decodes/prepares derivatives in one worker with one outstanding job, converts surfaces on the main thread, and keeps a bounded thumbnail LRU. Source images are limited to 40 million pixels before full decoding. Paint periodic saves use one immutable background snapshot, unchanged canvases are not encoded again, and recall prepares visible thumbnails asynchronously. Typing caches layout until relevant state changes and bounds recall reads. |
| 6: subprocess supervision | Launcher integration rejects unsupported subprocess commands in the supervised system; the Music integration owner maintains the embedded-runner registry. |
| 7: retention safety | Paint treats `max_archives` as capacity, clamps it to at least one, excludes quarantined corruption files, and refuses New/Recall replacement at capacity without deleting work. Typing defaults to 200 archives/256 MiB and also refuses further archives without deletion. Both leave a 16 MiB free-space reserve for current saves. |
| 8: post-replace failure | `CommitUncertainError` distinguishes visible replacement with unconfirmed directory durability. Regression checks preserve the old file before replace and explicitly expect the new visible file after a failed directory fsync. |
| 9: content/layout | Paint palette reflows into columns at short screen heights. Photos honors EXIF orientation, refreshes on entry, and discards stale worker results after selection/library changes. |

Controller restart now persists parent recovery and explicitly reconciles GDM after reporting readiness. Shutdown pins launcher identities using Linux pidfds, accepts cleanup acknowledgement only from the matching child UID/PID, and waits at most five seconds before killing an unresponsive process. Launcher integration sends the acknowledgement after activity/audio/display cleanup. Systemd restart/abort limits are explicit, and stale nonblocking socket readiness is tolerated.

Release installation and rollback serialize changes with a root-owned lock and fsync link replacements. Installation retains the previous target before activating the new one. Rollback requires parent mode, leaves the previous target identifiable, and refuses repeated no-op rollback; it is no longer a two-link toggle. New bundles require `data-schema.json` matching the installed release's data schemas. Already-installed unmarked releases use the established v1 schema. This is a compatibility declaration, not proof of correct migrations or that the previous release was qualified. Typing additionally preserves an unsupported `current.json` and stores this release's work in `current-v1.json`, avoiding destructive downgrade behavior.

At the repair checkpoint, the complete Python suite passed **146 tests**; further Music/integration changes have their own final validation record. A headless 100,000-character Typing example took approximately 117 ms for initial layout and 7–8 ms for subsequent cached frames, versus approximately 105 ms every frame at the baseline. These are workspace measurements, not HP benchmarks.

Remaining limits are concrete. Explicit Home/New/Recall saves may still wait for durable storage; the independent recovery deadline bounds a stuck application, rather than claiming the storage operation itself is cancellable. Directory enumeration/metadata work can depend on library size; Photos moves it off the frame loop, while Typing bounds candidate content reads to 200 records/16 MiB. Archive capacities deliberately require parent export/cleanup when full. Frame/save latency, multi-hour memory behavior, real SDL touch routing, audible Music timing, and HP graphics/input still require qualification.

Controller/socket/pidfd tests simulate kernel credential/readiness boundaries because this sandbox blocks SO_PASSCRED; `systemd-analyze verify` was also blocked by that restriction. Subsequent actual VM checks passed controller SIGKILL/SIGSTOP recovery, authenticated GNOME parent access, parent-mode persistence across reboot, the independent chord with a frozen launcher, and saved Typing work during parent transition. The final installer was also installed to a fresh VM disk and all four activities exercised; see [the integrated validation record](VALIDATION.md#music-and-repair-qualification) for release identities, evidence and limits. Full-guest ENOSPC, interrupted release switching, abrupt power cuts, extended operation and physical HP behavior remain qualification gates.
