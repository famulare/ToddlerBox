# Bootable ToddlerBox

The development target is Ubuntu 24.04 LTS on x86-64 UEFI. The same assembled
system disk produces the VM disk and the payload inside the USB installer.
No HP access is needed to build or test it.

## Build

On an x86-64 Linux host with Docker, `uv`, and at least 30 GB free:

```bash
./system/build.sh
```

Docker does not need privileged mode or loop devices. `system/versions.env`
pins the Ubuntu container digest, Ubuntu archive snapshot, and uv image digest.
`uv.lock` pins Python packages and their hashes; the setuptools build backend is
also pinned. Build artifacts include the actual dpkg package versions, a source
content ID that includes uncommitted code, and SHA-256 checksums.

This is a repeatable, versioned recipe, not a claim of bit-for-bit identical disk
images: filesystem timestamps, image metadata, and compression can differ.
Update the snapshot deliberately and requalify; installed systems retain the
snapshot source, so ongoing security updates require an explicit snapshot refresh.

For a TLS-inspecting build proxy, set `TODDLERBOX_BUILD_CA` to a trusted combined
CA bundle. It is mounted only during build, never installed in the product image.
Docker's normal proxy settings apply. Build logs contain no credential values.

Outputs under ignored `build/`:

| File | Purpose |
| --- | --- |
| `toddlerbox.qcow2` | Baseline VM disk; use overlays for tests |
| `toddlerbox.img` | Sparse, 12 GiB GPT system disk |
| `toddlerbox-installer.iso` | Bootable USB installer with the compressed identical disk |
| `SHA256SUMS` | Checksums of system artifacts |
| `packages.tsv`, `release-id` | Package versions and source release identity |
| `toddlerbox-app-<id>.tar.gz`, `APP-SHA256SUMS` | App release bundle and checksum |

The installer boots through GRUB in BIOS or UEFI mode, but the installed system
requires **x86-64 UEFI**. The initial qualification uses **Secure Boot disabled**;
the installer GRUB is unsigned. Do not infer Secure Boot qualification from the
signed Ubuntu shim/kernel present on the installed disk.

## VM development

```bash
./system/vm.sh start
uv run --no-project system/qmp.py screendump '{"filename":"/build/vm/screen.ppm"}'
./system/vm.sh stop
```

KVM is selected only when available; otherwise QEMU uses x86 software emulation.
The emulated CPU is `qemu64`; KVM uses `host`. QEMU's `max` CPU exposed AVX2
instructions that crashed GNOME's software renderer under TCG in this environment.
An ARM guest does not substitute for this test. The guest has 4 GiB RAM, two
virtual CPUs, a virtio display, and no network. The launch script never exposes
a listening VNC or SSH port. Connect a local VNC client to `build/vm/vnc.sock`,
or use QMP screenshots and input through `system/qmp.py`. Serial console and
logs are available at `build/vm/serial.sock` and `build/vm/serial.log`.

The first boot asks for the `parent` password on tty1. There are no default
passwords or built-in SSH keys. This is the same first-boot flow on hardware.
Use a disposable password for VM tests. Keep independent serial console access
open while testing the graphical session. `parent` can log in there and use sudo.

`build/vm/disk.qcow2` is an overlay on the built disk. Stop the VM before copying
it as a checkpoint or discarding it to reset. Do not rebuild/overwrite a base
image while an overlay that depends on it is running. Preserve the base with
any checkpoints you intend to keep.

For fresh-install testing, stop the running VM and run:

```bash
./system/vm.sh installer
```

This creates a separate 16 GiB target. Choose the serial installer menu entry to
operate from the serial console. Verify both cancellation and successful
installation. The installer lists disks and requires the exact phrase
`ERASE /dev/<target>` before writing; it refuses partitions, mounted targets,
the installation medium, and undersized disks. It verifies the compressed disk
checksum, streams the disk, expands the root filesystem, and powers off.
After shutdown, remove the stopped VM container with `./system/vm.sh stop`,
then use `./system/vm.sh installed` to boot that target without the installer.

## Sessions and recovery

GDM is the only graphical session manager. It starts the hidden, password-locked
`toddlerbox` account in a standalone Cage Wayland session. There is no GNOME shell
in that session. Cage runs without its VT-switching option. Power/lid/suspend
key inhibitors belong to this session only; no global keyd mapping is installed.
The child has no sudo rights and cannot write application releases or system
configuration.

Hold **Ctrl+Alt+Home for two seconds** to reach the parent GNOME login. A separate
root service reads input events, so the chord works when the app event loop is
stopped. The parent account must authenticate. The GNOME application menu has
**Start ToddlerBox**; save parent work before using it, because it ends the
current graphical session. Equivalent administration commands:

```bash
sudo toddlerbox-mode parent
toddlerbox-mode status
sudo toddlerbox-mode child
journalctl -b -u toddlerbox-controller -u gdm3
sudo journalctl -b _UID="$(id -u toddlerbox)"
```

The launcher, Paint, Photos and Typing report health only after processing and
rendering a frame. The controller allows 90 seconds for startup and 20 seconds
without a frame once running. It restarts the graphical session at most three
times per child-mode entry. Successful frames do not reset that budget. Exhaustion
opens parent login and persists a recovery latch across reboot. Explicitly
starting child mode clears the latch. The controller itself has a systemd watchdog.
Runtime session configuration is in `/run`, so disk-full does not block recovery.

The GRUB menu always offers **Parent recovery — Ubuntu GNOME login**. That bypasses
child autologin before the application starts. Serial login remains independent
of the graphical session. The installer recovery shell is an additional repair
route if even GNOME cannot start; it does not automatically erase anything.

## Preserved work and releases

Data lives in `/var/lib/toddlerbox`, independently of app releases. Paint saves
`paint/latest.png`; Typing saves `typing/current.json`. Both restore current work
on re-entry. Paint defaults to a ten-second save interval; Typing to five seconds.
Home and normal termination attempt an immediate save. Sudden power loss can
lose edits since the last successful save. Frozen or killed processes cannot
flush memory; the last committed file is the recovery point.

Writes use a temporary file, file fsync, atomic replacement, and directory fsync.
"New" clears only after archiving succeeds. Disk-full keeps work in memory and
prevents normal Home navigation when saving fails. Corrupt current files are
preserved for inspection. New Typing archives use separate atomic JSON files;
legacy `sessions.jsonl` archives remain readable. Physical power-loss behavior
still depends on the storage device honoring flushes.

App code and its uv-created environment live in `/opt/toddlerbox/releases/<id>`.
Runtime directly executes the installed Python environment and does not resolve
or download dependencies. To update from a trusted build of the same system ABI,
enter parent mode, copy the app bundle, and use its independently checked checksum:

```bash
sudo toddlerbox-install-release toddlerbox-app-<id>.tar.gz <expected-sha256>
sudo toddlerbox-mode child
```

The installer keeps `previous` before switching `current`. In parent mode,
`sudo toddlerbox-mode rollback` restores that previous app release. A first
installation has no previous release yet. Keep the last qualified system image
as the OS-level rollback artifact and back up `/var/lib/toddlerbox` before any
reinstallation; the USB installer erases its selected disk. App rollback does
not revert the OS or child data. Qualify a candidate before calling it known-good.

## Qualification gates

Record results and actual artifact IDs, not just intended behavior:

- Fresh disk boot and first-boot password setup; several clean reboots.
- Confirm the child session is Wayland/Cage and its session has no GNOME shell.
- Enter each activity, return Home, restore work after app exit and VM reset.
- Hold the parent chord during normal operation and after `SIGSTOP` of the app.
- Authenticate to ordinary GNOME, then return to child mode.
- Crash the app, freeze its event loop, and break startup; inspect bounded
  retries and parent recovery, including persistence across reboot.
- Test a corrupt photo, corrupt save, failed save, and a disposable full filesystem.
- Install from the ISO to an empty VM disk, reboot the installed disk, and repeat
  child/parent smoke checks. Cancellation must leave the target untouched.
- Run an extended soak while watching RSS, process counts, journal growth,
  frame progress and save behavior. A short smoke run is not a soak qualification.

Only then qualify the HP with a backup and a bounded checklist: UEFI/Secure Boot
settings; graphics; all touchscreen edges and multiple fingers; touch mapping;
keyboard and trackpad; power/lid behavior in each mode; sleep/resume in parent
mode; and repeated cold boots. Its exact model and existing session are still
unknown. No finding from this VM diagnoses its previous gesture escapes.
