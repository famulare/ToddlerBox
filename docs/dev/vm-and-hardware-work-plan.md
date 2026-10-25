# Dev VM and hardware work plan (`dev/review-hardening`)

This plan covers the testing that Claude cannot run from this Mac. It was agreed with
Codex `gpt-6-astra` on 2026-10-23.

## What can run where

| Executor | Can build the x86 image (Docker) | Can boot an x86 VM | Notes |
|---|---|---|---|
| Claude, local Mac | No | No | arm64 Mac with no Docker or QEMU. Runs unit and integration tests through uv. |
| Claude cloud session | No | No | No cloud environment is available for this project. |
| Codex, local Mac | No | Only through UTM via computer use, if UTM is installed | This continuation uses the existing local dev worktree. Cloud Docker/QEMU capability has not been tested. |
| **GitHub Actions** (ubuntu-24.04) | Yes | Yes (TCG, as the release workflow already does) | **Selected route. The owner approved dev pushes and Actions qualification, reaffirmed 2026-10-25.** |
| The owner, with Codex computer use | Indirectly | Through UTM | Fallback for route C. |
| The owner | — | — | Physical HP acceptance only. |

## Route A (preferred): dev-only GitHub Actions workflow

The owner has approved pushing the dev branch and running this workflow.

**Status:** the fresh-install job is implemented in `.github/workflows/dev-vm-qualify.yml`.
To run it, push `dev/review-hardening` with a head commit message containing `[vm]`.
`ci.yml` runs on every push. The second job, `update-chain`, consumes the exact
candidate bundle built by `fresh-install` and starts from public release assets.
It builds only the pinned VM tools again, not another candidate image. See
`VALIDATION.md` for execution evidence; implementation alone is not qualification.

**Verified 2026-10-25:** fresh-install job `40229180735` and update-chain retry
`40233346604` passed on the exact same built bundle. Built Git revision is
`9d12352`, application/system content `1f8bc04e1db6f2df`; the successful update
driver is `489f6bc`. The signed/public chain, dev signature, unsigned recovery,
exact rollback, all four real reset boundaries and final accepted reboot passed.
Compact results and the package manifest are preserved in
[`qualification-2026-10-25/`](qualification-2026-10-25/). Physical HP acceptance
and the separately listed image fault scenarios remain unverified by these runs.

- **File.** `.github/workflows/dev-vm-qualify.yml`, present only on `dev/**` branches.
  `workflow_dispatch` would require the file on the default branch, so the trigger is a push.
- **Trigger.** Pushes to `dev/**` whose commit message contains `[vm]`, so ordinary pushes
  run only `ci.yml`.
- **Permissions.** `contents: read`. No tags, releases, `stable.json` or signing keys.
- **Retry permissions.** `actions: read` also permits downloading a pinned candidate
  artifact from a previous run. Every token permission remains read-only.
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
     - The installed historical updater performs the signed upgrade. The harness
       never substitutes a new updater to make that test pass. The explicit
       unsigned recovery check uses the checksum-verified candidate zip bootstrap
       because the old command predates `--unsigned-recovery`.
     - A read-only published baseline backs a disposable overlay. Real durable
       `applying`, first changed installer replacement, `pending`, and interrupted
       `restoring` boundaries stop the responsible process before a QMP reset.
       Check the stopped process, candidate identity and durable journal before
       each reset; then verify the resident result and exact system/app rollback,
       synthetic Paint/Typing bytes, config and original resident files.
  4. **Separate planned image fault checks** (not performed by the update-chain job).
     - A Paint short write (the guest's data partition filled with a test file) and Home.
     - A read-only remount, then Home.
     - Sync with the fake rclone shim: a corrupt PNG and a case-duplicate pair in Photos,
       then SIGTERM during upload.
- **Runtime.** Expect each full run to take 100–150 minutes of TCG time. GitHub Actions
  minutes are free for public repositories.

Portable update-chain invocation (new output directory; Docker tools and public
downloads must already be present):

```sh
uv run --frozen python scripts/qualify-patch-update.py build/dev-candidate build/responsive-update-vm-NEW \
  --baseline-image-dir build/published/installer --baseline-version 0.4.0 --baseline-sequence 2 \
  --published-dir build/published --release v0.5.0:0.5.0:3 --release v0.5.1:0.5.1:4 \
  --candidate-version 0.5.1 --candidate-sequence 5
```

`installer/` contains `toddlerbox-installer.iso` and `INSTALLER-SHA256SUMS` from
v0.4.0. Each tag directory contains its published `stable.json`, signature and
`ToddlerBox-update.pyz`. The candidate's Git revision and content ID must match
the checkout. Sequence 5 is synthetic metadata for this VM run; source remains
version 0.5.1 / sequence 4. Test private keys exist only in host process memory;
the public key is injected only after the real signed chain succeeds. The bundle
bytes remain exactly the build's original bytes. Guests have no NIC.

New runs refuse existing outputs and have no resume bypass. The older positional
invocation and `--resume`/`--resume-recovery` are retained solely for the historical
qualified 0.5.0 checkpoint described in the 0.5.1 validation record. Evidence
artifacts contain only selected `checkpoint-*.png` screenshots and `results.json`;
no VM disks, raw serial logs or signing keys are uploaded. The candidate transfer
artifact expires after one day; evidence expires after fourteen days.

For a **harness-only retry**, a push containing both `[vm]` and
`[reuse-candidate]` skips the fresh build and fresh-install job. Update
`docs/dev/update-vm-candidate.json` deliberately to the exact prior run, built Git
revision, content ID and bundle SHA-256. `scripts/reuse-vm-candidate.py` checks
the completed dev workflow's repository/revision and successful fresh-install
job before downloading; the checksum and embedded source identity are checked
again after download. The qualification command receives
`--candidate-revision BUILT_GIT --candidate-sha256 BUNDLE_SHA256`. It still
requires the current checkout's entire application/system content ID to match,
so a runtime or README change cannot reuse that old bundle. The results record
built and qualification-driver Git revisions separately. The published installer
chain is repeated on a fresh disk, with no resume or fabricated journal bypass.

After preserving the published baseline, the harness waits at most sixty seconds
for the newly started QEMU serial socket to listen before authenticating. This
wait applies only to the test VM; production recovery deadlines are unchanged.

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
- **The installer USB.** Flash it with balenaEtcher, following the owner's private recovery notes (`RECOVERY.md`).
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
