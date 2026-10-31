# Paint latency investigation

Status: Phases 1–3 collected privately; durable renderer policy and final acceptance remain pending.
Owner branch: `dev/0.5.3-paint`. Follow-up: GitHub issue #29.

## Objective and current evidence

Explain why the same Paint candidate feels responsive on the parent desktop but
lags in the standalone child session. Measure before choosing another change.
The bounded Paint hardening is commit d7a0ff94a45ca601093252109931642e9adefad8,
content 29273cfc22b6d2bb. Its local candidate remains pending explicit acceptance.
The accepted 0.5.2 rollback must remain available.

Current evidence: unchanged brush/persistence function bodies; 778 Linux tests;
108 exact baseline/candidate full-frame comparisons; reduced synthetic rendering
CPU cost. A stopped-stroke mechanism after benign window notifications has a
regression test and fix. No proof connects it to a particular physical failure.
Synthetic rendering timing excludes physical input, compositor and panel latency.

Parent test: direct Paint, SDL Wayland, GNOME compositor, separate test data.
Child: embedded Paint, SDL Wayland, Cage forced to pixman, software renderer hint,
health/control IPC and real child data. Canvas contents/format, resolution/scale,
process embedding and presentation are confounders. SDL_RENDER_DRIVER alone does
not prove which path pygame.display.flip uses; inspect the actual implementation
or instrument it before attributing cost to that setting.

## Safety and privacy boundaries

- No exclusive device grabs, event injection, keyboard recording or raw coordinates.
- No child media, screenshots, typing text, credentials, setup packages or device
  identity in public evidence. Runtime reports stay local under ignored build/.
- Never run Cage nested inside GNOME as evidence for the production session.
- Parent escape and watchdog stay independent. Never change their timeouts to
  accommodate slow diagnostics. No background network activity or installation.
- Never mutate published artifacts or overwrite an accepted release directory.
- Keep one experiment variable at a time. Every temporary session override needs
  a root-owned original, automatic restoration and independently tested recovery.
- Local pending candidate acceptance/attempt limits must be inspected before more
  supervised starts. Do not reset counters or bypass recovery to prolong testing.

## Phase 1: bounded external baseline (first action)

Run scripts/collect-paint-session.py as a transient system service, bounded twice:
its own six-minute deadline and systemd RuntimeMaxSec=420. It survives desktop
logout. Collect once per second: parent/child mode, total CPU, allowlisted Paint/
launcher/Cage/GNOME CPU, available CPU frequency, touch down/up/motion/drop counts.
No coordinates, key codes, image data or arbitrary process/environment dumps.
Reports checkpoint once per second and carry a completed/interrupted marker.

Prepared local launcher (sudo authentication is required):

```sh
sudo /usr/bin/python3 /home/parent/toddlerbox/build/start-paint-baseline.py
```

It checks the actual installed candidate/start allowance before starting a
transient service. It refuses when another child test is unsafe. This local
launcher and the runtime reports live under ignored build/, outside source control.
The durable collector source is scripts/collect-paint-session.py.

1. Start collector in parent mode. Launch direct desktop Paint with its existing
   separate test folder. Draw slow curves and fast scribbles for about 20 seconds;
   stop moving and observe catch-up. Close with Esc.
2. Check the resident pending-candidate start allowance before switching. Start
   the real child session through normal authenticated maintenance. Draw the same
   kinds of strokes for about 20 seconds. Return through Ctrl+Alt+Home.
3. Resume Codex. Read the collector report, compare CPU and touch continuity across
   modes, and record uncertainties. Stop early if recovery or candidate allowance
   prevents testing. Do not infer frame latency from CPU samples.

This phase cannot separate drawing, flip waits or compositor queueing. It supplies
baseline load/input continuity and confirms the collector survives logout.

## Phase 2: opt-in application timing, controlled inputs

Prepare a separate journaled development candidate with diagnostics disabled by
default. Bound samples/memory/time; aggregate off the frame thread; no per-event
file writes. Measure event-batch count, accepted/rejected pointer events, drawing
work, autosave snapshot work, frame rendering, flip wait, clock.tick wait and frame
intervals. Correlate monotonic clock domains explicitly; do not call SDL/kernel
clock differences latency without verifying their origin and units.

Use identical synthetic RGB and opaque-RGBA canvases, dimensions, brush and stroke
inputs. Compare direct and embedded execution separately from compositor choice.
Record p50/p95/p99/max, frame count, sampling overhead and autosave boundaries.
Prove diagnostics do not change final pixels or saved files and cannot block Home.
If actual input events stop, investigate touch/gesture cancellation independently
from presentation. A simpler renderer cannot recover events never delivered.

## Phase 3: compositor A/B, only after baseline and recovery checks

Inspect the installed Cage/wlroots build and available DRM/EGL renderer support.
Test the same standalone Cage binary and app with only WLR_RENDERER changed from
pixman to supported GPU rendering. Keep the VM-compatible software default unless
hardware evidence supports a narrowly selected alternative. No GPU driver/package
changes in the first experiment. Do not assume the setting is supported or useful.
Use a bounded one-shot session override with automatic restoration before allowing
normal unattended startup. A failed start must return through existing recovery.

Compare frame/presentation distributions and human drawing response, not average
CPU alone. Optional slow-motion video measures physical finger-to-ink response;
software submission timestamps cannot establish panel response latency.

## Completion and decision

Choose the smallest measured improvement that preserves brush output, saves,
audio, six activities, supervision and parent escape. Keep #29 open until the
remaining lag/stopped-stroke reproducibility limits are stated accurately. Any
production change needs focused failure tests, Linux CI, exact source/build hashes,
real standalone physical testing and explicit parent acceptance. No automatic
acceptance or public stable-channel advancement follows from this investigation.

## Resume checklist

- Inspect current release, pending journal/attempts and last local collector report.
- Identify the last completed phase; do not repeat unchanged synthetic qualification.
- Record commands/results/limits here or in VALIDATION.md; keep raw local reports
  outside Git. Next action is Phase 1, then determine whether Phase 2 or a safe
  compositor A/B is justified by its evidence.

## Progress: first baseline and next measurement

The bounded external collector completed. Its report and analysis remain local
under ignored build/; do not publish appliance measurements or raw traces.
The next step is application-stage timing rather than attributing the difference
to compositor CPU load. CPU consumption is not a frame-latency measurement.

Opt-in Paint timing is armed only by a small root-owned, non-symlink, non-writable
flag `/run/toddlerbox-system/paint-timing.json` containing `expires_monotonic`.
The deadline must be in the next 600 seconds. With no valid flag it is disabled.
It records bounded histograms for event batches, render work, display flip,
clock.tick, frame intervals and autosave snapshot calls, plus pointer acceptance
counts and fixed display/canvas metadata. It never records positions or contents.
Each Paint visit gets a distinct local report under its data_root/logs directory;
a bounded daemon checkpoints it, so diagnostic file I/O never waits on the UI.
Expiry stops recording and the writer. No health/recovery limits are relaxed.

A new diagnostic candidate must use the resident update journal. If the existing
local candidate has used its two permitted starts, restore accepted 0.5.2 first,
then install the separate instrumented candidate. Never reset attempt counters
or accept an unapproved candidate to gain more test sessions. The parent must
authenticate the prepared local installation command; no live instrumentation
is enabled merely by pushing source.

Primary-source research, relevant to interpreting later experiments:

- SDL screen-surface acceleration is separately controlled from brush drawing:
  https://wiki.libsdl.org/SDL2/SDL_HINT_FRAMEBUFFER_ACCELERATION
- Inspect the exact SDL 2.32.10 implementation before interpreting renderer hints:
  https://github.com/libsdl-org/SDL/blob/release-2.32.10/src/video/SDL_video.c
- Historical hint behavior and its fixes are documented upstream:
  https://github.com/libsdl-org/SDL/issues/10061

Do not assume that setting SDL_RENDER_DRIVER by itself establishes the actual
framebuffer path, or that changing WLR_RENDERER will resolve the measured cost.

## Phase 3 implementation and next action

Stage timings from both modes were collected successfully. The raw reports and
analysis remain local. The next variable is Cage's renderer; do not change the
SDL renderer hint, app code, canvas dimensions or frame pacing during that trial.

The development session recipe now admits a gles2 trial only through the fixed
root-owned, non-symlink, exact-mode-0644 runtime flag. It validates a literal
`gles2` token, decimal Linux boot-time expiry (including suspend), no extra fields and a deadline within
300 seconds. Missing, malformed, untrusted or expired flags leave pixman selected.
The file lives in /run and cannot survive reboot. This is a journaled session
payload change, not an unjournaled replacement or a bind mount over a recovery
destination. Normal startup and the signed stable release are unchanged.

A separate bounded root observer removes the flag as soon as a gles2 Cage
process is observed so a subsequent compositor restart gets the original default.
It also removes the flag on termination and requests parent mode at its deadline
if the child session has not ended. ExecStopPost provides independent flag cleanup.
Existing controller escape, watchdog, retry limits and candidate recovery remain
in force. A failed trial must be reported, not worked around by resetting counters.

Install the new separate local candidate through the resident journal first,
rolling the previous pending diagnostic candidate back to accepted 0.5.2 if needed.
After parent login, arm the trial/timings, start the normal standalone child
session, draw for 30 seconds and return through Ctrl+Alt+Home. Do not run Cage
inside GNOME. Verify the override is removed before concluding the experiment.

## Resume after the renderer A/B

The bounded GLES2 trial ran and returned through the normal parent path. The
override was removed. Its timing/CPU reports and user observations remain local
under ignored build/; do not publish these private appliance measurements.
Do not confuse a successful one-shot trial with a durable startup setting or
acceptance of the whole candidate. Ordinary startup remains pixman at this point.

For the durable policy, inspect the exact linked wlroots implementation, not a
current-version summary. Upstream 0.17.1 renderer_autocreate tries GLES2 in auto
mode, but automatic pixman fallback is conditional on the backend lacking a
render node. GPU initialization failure with a render node is not covered by a
universal fallback guarantee. Keep this distinction in the implementation/tests.
Primary source: https://gitlab.freedesktop.org/wlroots/wlroots/-/blob/0.17.1/render/wlr_renderer.c

Next implementation boundary: choose a measured accelerated default for suitable
hardware while preserving the unaccelerated VM path, explicit software recovery,
existing root supervision and known-good 0.5.2. Verify both GPU success and failed
initialization before qualifying a durable session change. Do not simply turn
the temporary root-owned trial flag into a permanent always-on flag. No renderer
policy change or automatic acceptance has been performed after the A/B.
