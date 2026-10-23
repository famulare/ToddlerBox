# Dev VM and hardware work plan (`dev/review-hardening`)

This plan covers the testing that Claude cannot run from this Mac. It was agreed with
Codex `gpt-6-astra` on 2026-10-23.

## What can run where

| Executor | Can build the x86 image (Docker) | Can boot an x86 VM | Notes |
|---|---|---|---|
| Claude, local Mac | No | No | arm64 Mac with no Docker or QEMU. Runs unit and integration tests through uv. |
| Claude cloud session | No | No | No cloud environment is available for this project. |
| Codex (this account) | No | Only through UTM via computer use, if UTM is installed | No Codex Cloud executor with Docker or KVM. Cross-architecture emulation is slow. |
| **GitHub Actions** (ubuntu-24.04) | Yes | Yes (TCG, as the release workflow already does) | **Preferred route. Needs the owner's approval to push `dev/review-hardening` to the public repo.** |
| The owner, with Codex computer use | Indirectly | Through UTM | Fallback for route C. |
| The owner | — | — | Physical HP acceptance only. |

## Route A (preferred): dev-only GitHub Actions workflow

Claude prepares this. It runs only after the owner approves pushing the branch.

- **File.** `.github/workflows/dev-vm-qualify.yml`, present only on `dev/**` branches.
  `workflow_dispatch` would require the file on the default branch, so the trigger is a push.
- **Trigger.** Pushes to `dev/**` whose commit message contains `[vm]`, so ordinary pushes
  run only `ci.yml`.
- **Permissions.** `contents: read`. No tags, releases, `stable.json` or signing keys.
  Evidence goes only to workflow artifacts, which expire after 14 days.
- **Jobs.**
  1. **Build.** `system/build-compact.sh`, then the app tarball and `ToddlerBox-update.pyz`,
     unsigned.
  2. **Fresh install.** `scripts/qualify-release-vm.py` against this branch's installer ISO,
     using synthetic work only.
  3. **Update chain.**
     - Install the published, verified v0.4.0 installer (checksum checked against its
       `INSTALLER-SHA256SUMS`).
     - Apply the signed v0.5.0 and then v0.5.1 updates, using published metadata verified
       by the shipped key.
     - In the disposable guest, inject a synthetic VM-only signing key, then apply this
       branch's bundle twice: once signed with the synthetic key, once through the explicit
       unsigned-recovery path.
     - Then run rollback and the interrupted-update checks. This uses
       `scripts/qualify-patch-update.py`, parameterised for baseline, candidate, version and
       sequence.
  4. **Fault checks in the guest.**
     - A Paint short write (the guest's data partition filled with a test file) and Home.
     - A read-only remount, then Home.
     - Sync with the fake rclone shim: a corrupt PNG and a case-duplicate pair in Photos,
       then SIGTERM during upload.
- **Runtime.** Expect each full run to take 100–150 minutes of TCG time. GitHub Actions
  minutes are free for public repositories.

## Route B (fallback): Codex drives UTM on the owner's Mac

Use this only if the owner declines Route A.
1. The owner installs UTM (the official build from getutm.app or the Mac App Store).
2. Codex, using computer use, creates an x86-64 emulated VM:
   - q35, OVMF/UEFI, 4 GB RAM, a 16 GB virtio disk, virtio-gpu and USB tablet input
   - audio is optional
3. Boot the installer ISO. The ISO comes from Route A artifacts, or from a published
   release for baseline checks. **Erase only the VM's virtual disk.** The installer lists
   disks, so confirm the 16 GB virtio disk.
4. Run the manual checklist below and record screenshots. Expect this to be several times
   slower than Route A.

## Route C: the owner, through Codex

Use this if neither A nor B is available. Hand Codex this file and ask it to run Route B
step by step. Claude supplies the artifacts and the checklist results template.

## Manual VM checklist (Routes B and C, and spot checks on A)

Synthetic data only. Never use real family photos or credentials in a VM.

1. **First boot.** Mistype the password confirmation once. The retry prompt appears and the
   login works afterwards. (WP9; fresh image only.)
2. **Paint.**
   - Draw, tap New 20 times, open Recall: there is exactly one archive of the drawing and
     no blank duplicates. (WP2)
   - Fill the disk, then draw and tap Home: Home returns to the launcher. Re-enter Paint:
     the drawing is still there. Free the disk and request sync: the save is acknowledged.
     (WP1, WP3)
3. **Typing.** Press Esc in Paint, Typing and Photos: nothing happens. Home works. (WP3)
4. **Config.** As the parent, add a tab-indented line to `/etc/toddlerbox/config.yaml`,
   then start child mode: the standard six-tile launcher appears. The parent log names the
   config error. (WP4)
5. **Reading.** Corrupt one illustration in a test copy of the assets: Reading still
   opens, without that card. (WP5)
6. **Escape.** Ctrl+Alt+Home for two seconds reaches the parent login during each of the
   checks above.

## Physical HP acceptance (owner)

Only after Route A (or B) passes, on the exact final candidate:
- **The installer USB.** Flash it with balenaEtcher, following `~/ToddlerBox-private/RECOVERY.md`.
  Codex can drive Etcher via computer use, but the administrator prompt is the owner's.
- **Reaching the build.** Install fresh on the HP, or apply the update. Class C fixes
  (sync, boot gate, image) need a fresh install.
- **The existing checklist.** Run `RECOVERY.md`: touch, edges, speakers, Home, the
  two-second escape, sync star, and Drive Creations.
- **Added for this branch.**
  - Mash New, then check that there are no duplicate archives.
  - Mash Esc in Paint, Typing and Photos.
  - Hold a key in Typing for 30 s, then check that the app stays responsive.
  - Unplug Wi-Fi during a sync, then check that status reports a partial result honestly.
