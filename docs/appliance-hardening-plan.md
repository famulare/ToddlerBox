> Approved implementation plan. Execution is recorded in VALIDATION.md; parent instructions are in parent-maintenance.md. Planning-only statements below describe the review checkpoint, not the present release status.

# ToddlerBox appliance hardening plan

Planning baseline: `ea0dca7d9efcc01dc746733f6513a8f1d005110e`.
Current qualified installer: `a60a9ddeca41e3f6`, built from `9952ee142fd128aeec326161c01ddeb91166b155`.
This document proposes implementation; it does not claim the new behavior is built or qualified.

## Goal and scope

Make one HP installation dependable for a parent without development tools:
install, complete guided setup, use the child activities, perform explicit
maintenance, and recover from failure while preserving work. Keep the child UI
unchanged. Public source, release artifacts and support documentation contain
no family material or credentials.

Support Ubuntu 24.04 LTS, x86-64 UEFI, initially with Secure Boot disabled.
Qualify the existing HP as the reference machine after generic VM qualification.
No hardware certification fleet, new activities, installer partition editor,
remote administration service or full OS image rollback in this milestone.

## Existing foundations and gaps

- Cage is already standalone under GDM, with no child GNOME shell. The child
  account has no sudo access; restrictions are session-scoped.
- The independent controller already provides authenticated parent escape,
  frame-health supervision, bounded recovery, media keys and a persistent
  parent recovery latch. Keep these mechanisms.
- The newest image includes Wi-Fi firmware/backend, PipeWire/WirePlumber and
  a Cage tap-to-click patch. Packages are explicitly selected with
  `--no-install-recommends`; audit that selection rather than claiming it is
  a complete Ubuntu desktop installation.
- First boot currently sets only the parent password on tty1, then writes
  `setup-complete` and starts child mode.
- The updater verifies payloads, restricts destinations, journals replacement,
  preserves system/app backups and checks schemas. It currently requires a
  manually obtained bundle/checksum and manual interrupted-update rollback.
- Installed apt sources use the build snapshot. That is reproducible build
  provenance, not a continuing security-update policy.

## Invariants

1. Child input may reach a login screen but cannot obtain a parent session or
   privileged action without authentication. Parent escape and watchdog
   supervision continue during setup tests, sync, update downloads/preparation
   and application freezes. The short controller replacement interval instead
   requires child mode stopped, a durable parent latch and independent recovery.
2. Child work, config, persistent UUID and private Drive state remain separate
   from releases. Rollback never discards newly created work.
3. No default passwords, Git credentials, developer checkout or dependency
   resolution on the laptop. Public downloads use HTTPS without authentication.
4. Drive remains explicit-only (`ctrl-alt-s` or parent action), with no new
   timer, boot, network or update-triggered sync.
5. Downloads and privileged installation have distinct trust boundaries.
   Parent-writable files cannot become unchecked root commands or destinations.
6. Maintenance produces no child dialogs, scoring, overlays or notifications.
   Existing autosave, receipt overlay, app behavior and original icons stay intact.

## Delivery sequence

### 1. Hardware support and containment audit

Compare the current package set with Ubuntu's desktop hardware dependencies and
recommendations. Record explicit inclusion/exclusion reasons for networking,
firmware, input, audio, graphics, removable storage and power management. Retain
Ubuntu drivers and services; add only evidenced omissions. Include `gh` as a
parent convenience; the update path must also work without `gh` authentication.

Inspect session permissions and GNOME/Cage boundaries, including VT switching,
screen edges, multi-touch, keyboard shortcuts, compositor failure and power/lid
events. Fix concrete escape routes at their owning layer. Avoid global keyboard
restrictions that damage the parent desktop. Expose no new network listeners.

Acceptance: fresh boot identifies a Cage child session without GNOME shell;
parent authentication, escape during app/controller failure, bounded recovery
and boot recovery work. Synthetic input checks exercise mixed keyboard/mouse/
touch and stuck input; actual HP gestures remain a physical acceptance item.

### 2. Resumable parent setup and maintenance entry point

Add one parent desktop entry, **ToddlerBox Setup & Maintenance**, backed by a
simple terminal/text program and existing Ubuntu settings tools. No bespoke
polished GUI is required. Use fixed commands/arguments for privileged operations
and existing parent sudo/polkit authorization; never collect secrets into logs.

Keep the console password bootstrap. Once a password exists, start the normal
parent login instead of child autologin while setup is incomplete. The bootstrap
service must finish before GDM starts; graphical setup cannot run inside its
current blocking `Before=display-manager` unit. The controller owns this routing
and must retain boot recovery and failure-latch priority.

Persist versioned, root-owned setup progress atomically outside app releases.
Separate password-created, setup-in-progress and setup-complete states. Reboot
or interruption resumes unfinished setup. Migration of an existing
`setup-complete` installation must preserve its password and normal boot behavior;
offer the expanded checks through maintenance rather than silently re-locking it.
If power fails after `passwd` succeeds but before progress is recorded, recognize
the configured password without reading/logging its hash or resetting it. Resume
through ordinary authenticated parent login. Routing priority is boot/update
recovery, then incomplete setup, then ordinary child startup. A setup child-test
exception is temporary: reboot returns to unfinished setup. Checklist mutations
and child-test entry use authenticated fixed privileged actions; neither child
files nor a GDM/controller restart can mark setup complete.

Guided steps:

1. Explain authenticated parent escape and boot recovery; confirm the password.
2. Connect Wi-Fi through Ubuntu's network tools, or explicitly choose offline use.
3. Choose an output device, play a test sound, adjust volume and test media keys.
4. Test touch, tap-to-click/physical click and pointer dragging.
5. Enter the actual supervised child session for a short acceptance test, then
   use parent escape and authenticate back to continue setup. Treat this as an
   explicit temporary test entry, not setup completion.
6. Optionally import the private Drive package or open reconnect/setup guidance.
   Missing Drive configuration never prevents local use.
7. Show completed/skipped/failed checks and explicitly finish setup.

Offline operation is valid. A failed hardware check stays visible to the parent;
the parent can accept that limitation to proceed. Password/authentication and
the software recovery route are required. Re-running setup changes only the
chosen settings, preserves skipped options and never overwrites child work.

The same program offers setup checks, update, rollback, Ubuntu maintenance,
Drive controls, backup/export guidance and support report. Operations remain
parent initiated; closing it leaves the system usable.

### 3. Public release update path and trust

Publish a combined system/app update bundle alongside each qualified installer.
The current play installer has no matching published combined update asset;
build and qualify one rather than assuming its app archive is sufficient.

Define a small versioned release manifest: release/version, source ID, supported
Ubuntu/architecture/ABI, accepted data schemas, bundle asset name, size, SHA-256,
required updater version and signature key ID. Select qualified releases through
an explicit stable designation, not arbitrary newest tags or commits on `main`.
Current candidate prereleases do not silently become stable updates.
Put the channel designation and a monotonic release sequence inside the signed
manifest. GitHub flags are discovery hints. Reject replayed older releases during
ordinary update; explicit rollback selects the preserved known-good pair.

Authenticate manifests with a detached Ed25519 signature and a public verification
key embedded in the image/updater. Use a maintained Ubuntu verification library;
do not implement cryptography. The private maintainer signing key stays outside
the repository, images and laptop. Document release signing, key rotation and
the older-key compatibility window. Ordinary verification needs no user hash
comparison, GitHub login or Git credentials. An unsigned/mismatched manifest is
refused. Signing-key provisioning is a release prerequisite, not an invented
credential or a reason to stop the planning work.
Fresh images embed the initial key/verifier. An older installation without this
trust anchor needs a separately trusted migration; a downloaded executable
cannot establish its own authenticity. This milestone targets the new installer,
so that legacy bootstrap is documented separately rather than required in the
normal no-manual-hash parent flow.

Parent flow: **Check for updates → see version/change summary → Install → test
child mode**. Fixed public GitHub repository/release URLs, bounded HTTPS requests,
download-size/disk-reserve checks and private root staging are enforced. Validate
redirect destinations and manifest fields; never execute downloaded code before
authenticity and payload checks. API limits, unavailable network or interrupted
downloads leave the installed release running and allow an explicit retry.

Reuse the existing updater and locks. Record candidate versus known-working
state durably. After installation, an explicit child test uses real frame health
to confirm the candidate. Startup failure or exhausted recovery budget restores
the previous compatible system/app release and routes to parent recovery once;
never loop between releases or mark healthy solely because a process exists.
The candidate remains unconfirmed across reboot until a bounded real-frame child
test and explicit authenticated parent acceptance both succeed. Keep one known-good
system/app pair, refuse a second install while a candidate is pending, and commit
promotion atomically. Candidate/controller failures consume a durable bounded
attempt budget; restore the known-good pair once, then latch parent recovery.
Candidate-written data must remain readable by that older release; reject schema
changes without demonstrated backward readability in this milestone. Parents
retain a manual rollback option even after successful activation.

Before child boot, detect an incomplete update journal. Attempt validated bounded
rollback when the backup is complete; otherwise stay in parent recovery with
instructions. State this honestly: replacement of multiple system files is not
a whole-disk atomic transaction. Backups must remain usable across a changed
updater, including when the updater itself was interrupted or replaced. Keep a
small recovery entry point outside the replaceable candidate components.
This root-owned boot gate runs before both controller and GDM, uses a versioned
journal and fixed destination allowlist, and imports no candidate updater or
controller code. Keep it outside this milestone's replaceable bundle. Recovery
is restartable after another power cut. Missing/corrupt required journal or backup
selects authenticated parent recovery, never child autologin. Before replacement,
stop child mode and durably latch parent routing; block child entry and concurrent
apt/bundle mutations until the recovery gate or maintenance operation completes.

Acceptance includes power interruption at replacement boundaries, corrupt/missing
backup, bad signature/hash, wrong ABI/schema, low disk, download interruption,
concurrent maintenance and updating the updater/controller themselves. Demonstrate
that work created before and during candidate use survives rollback.

### 4. Ubuntu security maintenance

Separate reproducible build sources from installed maintenance sources. Preserve
the build snapshot/package manifest as provenance. On installed systems, use
Ubuntu's normal signed Noble release/updates/security repositories through a
documented migration, retaining apt signature and validity checks.

For this milestone, parent chooses **Ubuntu updates** explicitly. Apply normal
Noble release/updates/security package upgrades, including applicable security
fixes; do not label this as a security-only filter.
Show the last successful check and reboot requirement in parent mode; do not
interrupt a child session. Do not silently enable unattended installation or
kernel reboot. Recommended monthly parent maintenance is documentation, not a
new background scheduler. Ubuntu package changes are not covered by ToddlerBox
bundle rollback; preserve bootable recovery media and previous kernels where
Ubuntu normally does so. A security-source outage must leave the laptop usable.
Audit apt timers and unattended-upgrades so no automatic package installation
contradicts this policy. Handle interrupted `dpkg` state through parent maintenance
before further installs, and identify when the running kernel requires a reboot.

### 5. Parent status and support

Show release/build identity, setup results, network/backend status, audio output,
free disk, last successful save/backup where evidence exists, Drive's recorded
status, and maintenance/recovery state. Distinguish unavailable, never-run,
partial and successful results. Avoid calling an upload a complete backup of
the laptop or promising a fresh save when only an older file is durable.

Create diagnostics from an allowlist with bounded commands/time/output sizes:
versions, service states, sanitized failure codes and opt-in hardware IDs. No raw
recursive logs/config uploads. Exclude work/photos/text, credentials, tokens,
Wi-Fi names/MACs, serial numbers, account details and private file paths by default.
Test with synthetic secrets, identifying values and hostile input.

Parent reviews a locally saved report. **Report a problem** opens a prefilled
public GitHub issue in the normal parent browser; no automatic upload or issue
creation. Submission requires browser GitHub login. Provide copy/download fallback
for offline use, no account or URL length limits. Explain that posting makes the
reviewed report public. `gh` must not require a stored token for ordinary use.

### 6. Qualification and delivery

Record the actual baseline and frozen tooling; compare genuine old/new source
under identical inputs. Deterministic unaffected rendered frames, saved work and
existing media must match exactly. Add focused Linux IPC/controller/state-machine
and failure tests; run the complete suite. Update the product contract and
VALIDATION with observed behavior, commands, identities and limits.

Use existing golden disks/checkpoints as immutable bases. Fresh-install a new
x86 VM from the new ISO. Qualify offline setup, interrupted/resumed setup, skips,
repeat setup, authenticated child-test transitions, release download/install,
failed activation/rollback, interrupted-update boot recovery, parent reporting
and Ubuntu maintenance. Networked tests use public releases or synthetic HTTP
fixtures and package mirrors only; no real Drive or family data on the builder.

Record pass/fail, selected release, authentication and preserved work for each
boundary below. Recovery selection is software behavior; successful GNOME login
still depends on a working OS graphics stack, with console/USB recovery available.

| Injected boundary | Expected next state |
| --- | --- |
| Password set, progress write interrupted | Existing password retained; authenticated unfinished setup |
| Reboot during setup child test | Authenticated unfinished setup; no completion marker |
| Candidate installed but unconfirmed | Pending candidate/test state; original known-good pair retained |
| Power loss during promotion | One committed promotion state; no ambiguous release selection |
| Power loss during rollback | Boot gate resumes restore or selects parent recovery |
| Broken candidate updater/controller | Independent gate restores known-good pair or selects recovery |
| Malformed required journal/incomplete backup | Parent recovery, child autologin disabled |
| Child-entry request during installation | Refused until maintenance/recovery completes |
| Older signed release replay | Refused; current installation unchanged |
| Interrupted apt operation | Parent dpkg repair route; no claim of app rollback undoing packages |

Exercise all six child screens, actual audio, input failures and independent
escape/watchdog during stalled maintenance/sync. Inspect observable screenshots
and saved outputs; a mocked drawing call is insufficient. Capture parent UI
screenshots for the PR. Publish a checksum-identified ISO, combined update bundle,
signed metadata, source/package manifests and concise install/update instructions.
Never describe VM validation as physical HP validation.

At the end, ask Mike for a reviewed hardware report and a short HP test: repeated
boots, Wi-Fi discovery/connect/reconnect, speakers and volume keys, trackpad,
all edges/multiple fingers/drag, parent escape under a freeze, suspend/resume and
one parent update/rollback. Match CPU/RAM/display/UEFI in the VM where useful;
Wi-Fi radio, touchscreen firmware and real storage power-loss behavior cannot
be faithfully certified by that configuration.

## Review and implementation boundaries

Astra medium completed a read-only review on 2026-10-04. It judged the scope
practical and requested explicit boot-gate ordering, durable candidate promotion,
password interruption handling, controller replacement boundaries, initial trust
and replay policy, and apt maintenance semantics. Those adjustments and the
boundary matrix above are incorporated. No runtime implementation or new image
qualification occurred during this planning review.
Implementation proceeds in small reviewable changes: support/containment, setup,
release/recovery, maintenance/support, then the final image. Preserve qualified
artifacts and avoid unnecessary rebuilds until integrated qualification.
Respect Mike's request to keep effort within roughly 10% of the weekly budget;
actual account quota is not visible here, so avoid broad agent campaigns or
promising a measured quota. This planning pass does not implement runtime changes.
