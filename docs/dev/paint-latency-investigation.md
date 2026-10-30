# Paint latency investigation

Status: active; baseline collection prepared, no renderer experiment performed.
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
