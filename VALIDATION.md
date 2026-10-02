# Bootable system validation — 2026-10-02

The [Reading qualification](#reading-application-qualification) below is the
current result for release **`c12b9037f41f5f85`**. Earlier sections retain the
shared interface, Music/repair and initial system results as historical evidence.

This is a development baseline for VM iteration. Hardware, extended operation,
and the remaining failure cases below still require qualification before using
it as the child's everyday system.

## Environment and evidence

The builder is x86-64 Linux with Docker's vfs storage driver. There is no KVM
device or physical graphics/touch hardware available. Guests use QEMU TCG,
`qemu64`, OVMF UEFI, two virtual CPUs, 4 GiB RAM, virtio graphics/disk, a USB
tablet, and no network. Screenshots and keyboard input use local QMP; a separate
serial login provides diagnostics even when the graphical application is frozen.

In this managed workspace, Docker commands used the local socket explicitly:

```bash
export DOCKER_HOST=unix:///var/run/docker.sock
export BUILDX_CONFIG=/workspace/.cache/buildx UV_CACHE_DIR=/workspace/.cache/uv
unset DOCKER_CONTEXT DOCKER_TLS DOCKER_TLS_VERIFY DOCKER_CERT_PATH
```

The inherited Docker proxy configuration was retained. No network access is
needed by a running guest or by the finished installer.

QEMU's `max` CPU caused GNOME's software renderer to crash on AVX2 instructions
under TCG. The `qemu64` configuration passed the desktop checks. This is a VM
configuration finding, not a diagnosis of the HP laptop.

## Completed checks

The initial integrated qualification used release `88ac086773976b6a`:

| Check | Observed result |
| --- | --- |
| Fresh image boot | First boot required creation of the parent password; no default password |
| Standalone child session | GDM started Cage on a Wayland seat; no child GNOME shell; fullscreen launcher visible |
| Parent recovery with a frozen app | After SIGSTOP, holding Ctrl+Alt+Home switched to parent login and terminated the stopped app |
| Parent desktop | Password authentication reached Ubuntu GNOME; no repeated renderer crashes with `qemu64` |
| Return to child | Administrative child-mode command restored the launcher and healthy frames |
| Saved work | Typing autosaved `savedwork`; the document restored after forced termination, reboot, and return to child mode |
| Repeated hangs | Four successive SIGSTOP injections produced exactly three restarts, then a persistent parent recovery latch |
| Recovery reboot | Parent mode persisted across reboot |
| App release switching | Installed a second bundle, retained the previous release, rolled back to `88ac086773976b6a`; saved typing remained unchanged |
| Rollback without a previous release | Refused with a nonzero command result |
| Installer cancellation | Incorrect erase confirmation left the blank VM target untouched |
| USB installer path | Booted ISO, verified payload checksum, wrote 12 GiB disk, expanded root to the 16 GiB target, powered off |
| Installed disk | Booted without ISO, required parent setup, entered healthy child mode, then reached GNOME parent login |

The installer test exposed BusyBox replacing the standard `dd` path during
initramfs generation. The recipe now bundles GNU dd at a dedicated path; the
successful installation used that correction. The final release also narrows
shutdown signals to the Python application, preserving its opportunity to save
before the compositor is stopped. Build assembly releases its temporary export
container before constructing disks to reduce peak storage use.

Local evidence is retained under ignored `build/`: `vm/fault-result.log`,
`vm/rollback-result.log`, `vm/qualified-restored-typing.png`,
`vm/qualified-parent-desktop.png`, `install-vm/install-result.log`,
`install-vm/installed-result.log`, and `install-vm/installed-parent.png`.
VM password files are disposable local test credentials and are not in images
or tracked source.

## Automated checks

`uv run --offline pytest -q`: **65 passed**. Coverage includes interrupted
writes, failed fsync, simulated ENOSPC, preserving previous saves and in-memory
work, current-document restoration, corrupt-save preservation, legacy typing
archives, startup retry exhaustion, and the independent escape chord.

Shell syntax, systemd unit verification, and `git diff --check` passed. Image
assembly compares the raw and QCOW2 disks byte-for-byte with `qemu-img compare`
and generates artifact SHA-256 checksums.

## Final build artifacts

The completed build produced release **`f903c7e5135a9dc9`**, using Ubuntu 24.04
and kernel `6.8.0-142-generic`. `build/final-build.log` records the successful
build and raw/QCOW2 comparison. All three checksums were independently rechecked
with `sha256sum -c SHA256SUMS`:

```text
a1e0006f2beff01d3b2e4d60be2b64a94fc03fda7b41fc9e6d0476821e208e8e  toddlerbox.img
64764ea45c933eb711f79fb16ba01c8b2d9f5770cd8b6a54b6191d6bea82180c  toddlerbox.qcow2
c6f088371851de553761b42c0bf6f3d9b5c0a58417b40d1e3dcc120f10133ee8  toddlerbox-installer.iso
```

The host VM helper subsequently gained separate UEFI variable files for baseline
and installation disks. Reusing the baseline firmware state had selected the
UEFI shell instead of the installer. Fresh firmware booted the final ISO. This
helper-only change does not modify the system image or its release identity.

The final ISO was then installed to another fresh 16 GiB VM disk. Payload
verification, disk writing, filesystem expansion, shutdown, first boot, and
parent password creation passed. The installed release reported
`f903c7e5135a9dc9`, a 16 GiB root filesystem, healthy child frames, and zero
retries. Paint drew and restored a stroke after returning Home; Photos opened
its empty-library view; Typing saved `finalwork`. Evidence is in
`build/vm/final-install-result.log`, `final-installed-result.log`,
`final-launcher.png`, `final-paint-restored.png`, `final-photos.png`, and
`final-typing.png`.

On the final release, entering parent mode saved the newly added `z` in
`finalworkz`; returning to child mode produced healthy frames. SIGSTOP followed
by the two-second parent chord removed the frozen Python process and reached
the GNOME parent login. The first GNOME greeter took roughly a minute to become
usable under TCG; this is not a hardware recovery-time measurement.
Parent password authentication then reached the ordinary GNOME desktop on the
final release (`final-parent-desktop.png`), with an active parent seat session
and no kernel-reported segfaults during this boot.
Selecting **Start ToddlerBox** from GNOME search and authenticating through
polkit returned to the fullscreen child launcher, with healthy frames and zero
retries (`final-returned-child.png`). The final installed test disk is retained
at `build/vm/install-target.qcow2`; the VM was shut down after validation.

## Remaining qualification

- Physical USB boot/install, HP graphics and touchscreen edges/multiple fingers,
  keyboard/trackpad mapping, cold boots, and parent sleep/resume.
- Secure Boot: the initial installer is unsigned; qualification requires it disabled.
  The installed system requires x86-64 UEFI, even though the installer also boots BIOS.
- Extended soak with memory, process, log, and save measurements.
- Whole-guest disk exhaustion and abrupt virtual power cuts during saves; simulated
  write failures are covered, but they do not establish physical storage behavior.
- Deliberately broken startup in the VM, beyond the unit coverage of retry
  policy; explicit GRUB parent-recovery selection. Controller KILL/SIGSTOP
  recovery was subsequently qualified below.
- Installation refusal cases beyond cancellation: undersized targets, mounted
  filesystems, installer-media targets, and damaged payloads.

The existing HP session and the cause of its previous instability remain unknown.

## Music and repair qualification

The integrated implementation is committed in `fbee06e` (Astra repairs) and
`b28d7eb` (Music and integration). The final build is release
**`e65218acd46d664e`**, produced by `./system/build.sh` from the shared Ubuntu
24.04 recipe. `build/music-final-build.log` records the build and successful
raw/QCOW2 comparison. The release ID matches `system/source-id.py`; generated
Python package metadata is excluded from that identity.

### Automated and asset checks

- `UV_CACHE_DIR=/workspace/.cache/uv uv run --offline pytest -q`:
  **178 passed**. This includes pointer ownership/duplicate suppression,
  drawing/save regressions, bounded caches and archives, preservation on storage
  errors, release compatibility, and Music playback/state/cleanup behavior.
- Shell syntax and `git diff --check` passed. Controller credential/pidfd tests
  use simulated boundaries where the workspace sandbox blocks kernel operations;
  the real guest controller checks below complement them.
- Regenerating all 14 Music outputs offline produced byte-identical files.
  Preparing the piano inputs again from the cached, pinned upstream samples also
  reproduced the committed inputs. Six decoded tracks contain audio without
  clipping, have initial onsets within 50 ms of their first cues, and end quietly.
  These are asset measurements, not physical speaker latency or human listening.
- Launcher and Music screenshots were inspected at 1024×600 and 1366×768.
  The committed [Music screenshot](assets/screenshots/music.png) illustrates the
  passive keyboard visualization. Source, arrangement, instrument and recording
  provenance is recorded in [the asset documentation](assets/music/README.md).

### Actual guest checks

Recovery fault injection used release `53cf9f20f23af22c`. Its application,
controller and bundled Music code/assets match the final release; subsequent
changes corrected the host's fresh-overlay UEFI state and source identity
calculation. The final release was separately installed and exercised below.
Guests used x86-64 TCG, a standalone Cage Wayland child session, PipeWire and
emulated Intel HDA, with QEMU recording audio to a WAV file.

| Check | Observed result |
| --- | --- |
| Child session | Fullscreen four-activity launcher, healthy frames, zero retries, no child GNOME shell |
| Music output | Nonzero captured PCM; selection, automatic track advancement and resumed playback produced output |
| Controller SIGKILL during Music | Systemd restarted the controller in persistent parent mode; old child exited and audio capture stopped advancing; GDM was active |
| Controller SIGSTOP | The 10-second systemd watchdog aborted the stopped controller; restart reached persistent parent mode, removed the old child and activated GDM |
| Parent authentication | Password login reached the ordinary GNOME desktop after recovery |
| Recovery reboot | Parent recovery latch survived reboot; the greeter remained available |
| Independent parent chord | With the launcher deliberately stopped, holding Ctrl+Alt+Home for 2.5 seconds entered parent mode and removed the frozen process |
| Final ISO installation | Booted the final ISO on a fresh 16 GiB target, verified its payload, wrote the disk, expanded ext4 and powered off |
| Installed final disk | Booted without the ISO, completed parent password setup and entered healthy child mode; release ID and all six bundled WAV hashes matched |
| Installed Music | Played from the installed disk and advanced automatically through the song list to Minuet |
| Installed pause/resume | Paused note-field screenshots matched exactly and captured PCM was zero; playback resumed afterward |
| Installed Home cleanup | Returning Home from Music produced zero captured PCM |
| Installed Paint | A single-click dot remained after Home and re-entry |
| Installed Photos | Opened the empty-library view |
| Installed Typing | `musicready` restored after Home and re-entry; the added `z` was present in `current.json` after parent transition, yielding `musicreadyz` |

The final installed root filesystem reported 16 GiB with approximately 13 GiB
available. Local logs/screenshots are retained under ignored `build/vm/`:
`music-controller-kill.log`, `music-controller-stop-verified.log`,
`music-reboot-parent-status.log`, `music-app-chord-recovery.log`,
`music-parent-desktop.png`, `music-final-installer.log`,
`music-installed-status.log`, `music-installed-playing.png`,
`music-installed-pause-a.png`, `music-installed-pause-b.png`,
`music-installed-home.png`, `music-installed-paint-restored.png`,
`music-installed-photos.png`, `music-installed-typing-restored.png`, and
`music-installed-parent-save.log`. Disposable VM credentials remain local and
are excluded from source and installation media.

### Final artifact checksums

All system and application bundle checksums were independently verified:

```text
eb73f17803f7702633a734ab14961d234b5ca0c3f199923515f95bab9dfce6f3  toddlerbox.img
b85540b157d15423cfe22095e3a3e732a3718d2190547ea987a181104e82dc2e  toddlerbox.qcow2
7b01f930389c8eadf41fb1d5dcd388b798f90d6bd9d82c6cd29e75b9ab09640c  toddlerbox-installer.iso
48652ba0e32c9ea40396eff4b51b9bad5b9e77195041302ce635c723dc5e9ca7  toddlerbox-app-e65218acd46d664e.tar.gz
```

### Limits of this qualification

Physical HP touch routing and edge gestures, graphics, keyboard/trackpad,
speaker volume and audiovisual timing, USB installation, and sleep/resume still
need hardware qualification. Human listening to the arrangements and a
multi-hour representative-content soak are also outstanding. The existing
whole-guest ENOSPC, abrupt power-cut, interrupted release-switch, startup and
installer-refusal gates remain open; simulated storage failure tests do not
establish durability on the HP. The Music changes do not require a network at
runtime, and no claim of physical hardware validation is made.

## Shared interface qualification

The shared theme is implemented in `17bda97` and `9d75b46`. All four activities
use the same background, card, typography and selection colors, with a common
58px Home control. The original app/tool/Home artwork is retained; Music adds
a matching illustrated launcher icon. Document geometry, Paint pixels and
persistence/recovery algorithms are unchanged.

- **178 tests passed** after the final icon changes.
- Screenshots were inspected at 1024×600 and 1366×768, including empty and
  populated Photos, and the [combined preview](assets/screenshots/overview.png).
- Release **`6bf84a8245b3f9b6`** uses the existing pinned Ubuntu base and image
  tools with the current `Dockerfile.release` and `make-images.sh` recipe.
  `build/style-final-build.log` records successful assembly, filesystem checks
  and identical raw/QCOW2 contents. The source identity matches the checkout.
- All four artifact hashes were independently verified. The new ISO contains
  the same assembled system payload as the VM disk. The ISO's erase/write/expand
  installation path was qualified in the preceding Music release; this visual
  update does not change that path.

The final disk booted in a fresh x86-64 UEFI/TCG overlay, completed parent
password setup, and entered a healthy standalone Cage child session with zero
retries. All four activities were opened through the illustrated launcher;
their common Home control returned to the launcher. Paint's single-tap dot and
Typing's `style` text restored after Home and re-entry. Music produced nonzero
captured PCM during playback (peak 3751) and zero PCM after Home. A parent-mode
transition then preserved `style` in the current Typing document and stopped
the child cleanly. Evidence is under `build/vm/`: `style-guest-status.log`,
`style-smoke.log`, `style-overview.png`, and the individual `style-*.png` captures.

```text
11f134be07e7117ad7c9b08aa24772b9f3fe76c1c3b82da73a9cb1d30cbbbe78  toddlerbox.img
1881810c49f7fa7744884d75d120ba0bef294fcab71e2685e76b7316d0e8f8e8  toddlerbox.qcow2
5b9a8675936a9d3df886a923bcd909eeddccbb9c681b7b99df680030204c38aa  toddlerbox-installer.iso
e1f4d7853b7538a25b7a77a0639328edc211e79d05913d109c4dc51e1c7db725  toddlerbox-app-6bf84a8245b3f9b6.tar.gz
```

### Bounded extra storage check

Astra independently used a disposable overlay over the qualified `e65218acd46d664e`
installed disk; the base disk was mounted read-only and its modification time
remained unchanged. Installed application save methods targeted a 32 MiB ext4
loop filesystem inside that guest. Filler writes reached actual ENOSPC.
Typing's attempted save returned failure, and subsequent independent read-only
inspection found the valid previously committed text `prior`, preserving it
against the attempted `priornew` replacement.

This is one actual guest data-filesystem save-failure observation. Paint's tiny
PNG still fit in the remaining space, so its expected-failure assertion did not
pass and the rest of that test was not reached. Whole-root exhaustion, controlled
power cuts, and Paint preservation under actual ENOSPC remain open. Host build
storage exhaustion also occurred during follow-up; the agent stopped new fault
writes and kept later inspection read-only. That host event is not a guest
storage-test success. Evidence and limitations are retained in ignored
`build/storage-qa/RESULTS.txt`, `serial.log` and `enospc.sh`.

The installer build was completed after reclaiming disposable build staging,
unused intermediate Docker images and build cache. Qualified VM disks were
preserved. Physical HP, listening, extended-operation and other previously
listed qualification limits remain unchanged.

## Reading application qualification

Reading adds 30 illustrated words, alphabet sound/name decks, and numbers 0–30.
The shared launcher now fits five icons in centered rows where required.

- **201 tests passed** in 4.14 seconds: 178 existing tests plus 23 Reading checks.
- All **158 source assets and 189 prepared outputs** passed SHA-256 verification.
  A separate rebuild reproduced every prepared file and catalog byte-for-byte.
  Independently regenerating all 31 number WAVs with the locked Piper preparation
  environment reproduced their hashes exactly.
- Screens were inspected at 800×600, 1024×600, 1280×800 and 1366×768, including
  the word-first, sound-highlight and picture states, letters, numbers and the
  five-icon launcher. Automated layout coverage also includes 1024×768.
- A bounded dummy-SDL run made **1,000 random selections** after 100 warm-up
  selections with no immediate repeats. RSS increased from 32,984 to 34,428 KiB;
  the maximum selection-plus-render time was 9.245ms. This is a short local
  allocation/responsiveness check, not a multi-hour hardware soak.
- Source/derived media licenses and the differing recorded voices are documented
  in [assets/reading/README.md](assets/reading/README.md). Original media and
  editable drawings are included. Human listening/pronunciation review remains
  outstanding; decoding and waveform bounds do not establish pedagogical quality.

### Built system and actual guest checks

Release **`c12b9037f41f5f85`** was built with `./system/build.sh` from the shared
Ubuntu 24.04 recipe. Filesystem checking, raw/QCOW2 comparison and independent
verification of all four artifact checksums passed. The source identity matches
the application/configuration used for these checks.

The fresh x86-64 UEFI/TCG overlay required parent password creation, then opened
the five-activity launcher in standalone Cage. The controller reported healthy
frames, zero retries and no child GNOME shell.

| Check | Observed result |
| --- | --- |
| Word-first interaction | The initial card had no picture; tapping played the sequence and revealed the illustration |
| Captured speech | Nonzero PCM, peak 7276; this verifies output, not pronunciation or physical loudness |
| Next and Home | Next changed the word; both controls interrupted speech and subsequent captured PCM was zero |
| Shared audio | Music → Reading → Music worked in the shared process |
| Other activities | Paint's dot and Typing's `reading` restored after Home/re-entry; Photos opened |
| Parent-selected decks | Lowercase sounds, uppercase letter names, and number 23 played and revealed their illustration/quantity |
| Actual data ENOSPC plus damaged media | A dedicated 16 MiB ext4 loop filesystem reached zero available bytes; a 4096-byte write failed ENOSPC. With this as Reading's data root and a corrupt `cat` sequence, remaining cards still played/revealed, Next/Home worked, and the controller retained zero retries |
| Independent frozen-app escape | After SIGSTOP during Reading, the held parent chord removed the stopped launcher, persisted the parent latch, reached GNOME login and left zero captured PCM |

The recovery harness's first fixed 12-second host wait was too short under TCG.
Subsequent independent serial checks confirmed parent mode, absence of the stopped
PID, and the controller's exact reason: `Ctrl+Alt+Home held for two seconds`.
This is not a physical recovery-time measurement. The storage fixture was removed,
the original configuration restored, and the original recording hash rechecked.
This bounded Reading test does not qualify whole-root exhaustion or Paint saves.

The final ISO then installed onto a separate blank 16 GiB virtual disk. Payload
verification, disk writing, filesystem checking/expansion and shutdown passed.
Without the ISO attached, that disk required parent password setup and reached
healthy child mode with zero retries. Its root filesystem reported 16 GiB with
13 GiB available; all 189 Reading output hashes matched. Reading played speech
(captured PCM peak 7284), revealed its picture, and stopped cleanly on Home
(zero PCM). Typing saved `reading`, and an administrative transition entered
persistent parent mode.
Password authentication started an active parent seat session with `gnome-shell`;
an administrative return to child mode restored the fullscreen launcher, healthy
frames and zero retries. The saved Typing text remained `reading`. Parent session
authentication/process state was verified over serial; the desktop's finished
render was not separately captured in this Reading pass.

Local evidence includes `build/reading-final-build.log`, `build/reading-preview/`,
`build/reading-rebuild/`, `build/reading-number-check/`,
`build/reading-selection-check.json`, and `build/vm/reading-{guest-status,smoke,decks,storage-fault,recovery-verified}.log`.
Screenshots and captured audio are retained under ignored `build/vm/`.
Installer evidence is in `build/vm/reading-installer.log`,
`reading-installed-status.log`, `reading-installed-smoke.log`, and
`reading-installed-results.json`, plus `reading-installed-parent-status.log` and
`reading-installed-return-child.log`; the installed disk is retained at
`build/reading-install/disk.qcow2`. Earlier qualified disks were preserved.

### Artifact checksums

```text
6f34008d9526e3a9a72cf66ef6d2b962071698f498d40d66d661f34cf02a7b23  toddlerbox.img
5eff20ed23636c84f7f1edebb93486d255eafa1afde36980090559d6f81cb4a9  toddlerbox.qcow2
059af6824818796db59aa35d4ad0ca086e788e81e1a94782c579ac41cb86ecb4  toddlerbox-installer.iso
f2b66b58b8be1c994937c9c9c27f5e7850ac1d0ac0d5e0aa666ac1a9f7e9b3c8  toddlerbox-app-c12b9037f41f5f85.tar.gz
```

HP touchscreen/graphics/speakers, USB boot on physical hardware, sleep/resume,
human listening and multi-hour operation remain unqualified. Earlier open
whole-root/power-cut/startup/installer-refusal gates also remain open.

## Preparing a USB after qualification

Check `build/SHA256SUMS`. In Ubuntu Disks, select the intended USB device and use
**Restore Disk Image** with `build/toddlerbox-installer.iso`; this replaces the
USB's contents. Boot it on the backed-up target computer in UEFI mode. The
installer separately identifies the internal target disk and requires an exact
erase phrase before replacing that disk. On first boot, set the parent password.
Preserve `/var/lib/toddlerbox` before any reinstallation.
