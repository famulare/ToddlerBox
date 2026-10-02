# Bootable system validation — 2026-10-02

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
- Deliberately broken startup and controller failure in the VM, beyond the unit
  coverage of retry policy; explicit GRUB parent-recovery selection.
- Installation refusal cases beyond cancellation: undersized targets, mounted
  filesystems, installer-media targets, and damaged payloads.

The existing HP session and the cause of its previous instability remain unknown.

## Preparing a USB after qualification

Check `build/SHA256SUMS`. In Ubuntu Disks, select the intended USB device and use
**Restore Disk Image** with `build/toddlerbox-installer.iso`; this replaces the
USB's contents. Boot it on the backed-up target computer in UEFI mode. The
installer separately identifies the internal target disk and requires an exact
erase phrase before replacing that disk. On first boot, set the parent password.
Preserve `/var/lib/toddlerbox` before any reinstallation.
