# Issue #27: parent diagnostic tools in future images

Baseline: main b3d87f95bd160cf5de538f122e6b9537fd82370a plus the
0.5.3 development changes at branch base
411f71294797b83569b63385bc072b870a114258. Before this change,
`system/packages.txt` lacked libinput-tools, evtest, smartmontools and pciutils.
The image already included alsa-utils, pulseaudio-utils and PipeWire. #19 is
accepted/closed; its supported bounded `audio_check` / pw-play path is retained.

This change adds the four packages to the shared base/compact image recipe.
It creates no child controls or jobs and changes no signed app update payload.
Existing appliances receive no automatic apt installation. No live packages were
installed, no image was built on the HP, and the accepted/qualifying artifacts
were left unchanged.

## Package inspection

On 2026-10-31, `apt-get download smartmontools libinput-tools evtest pciutils`
downloaded archives into `/tmp/tbx-issue27-packages`; `dpkg-deb -R` inspected
payloads and maintainer scripts without executing them. Local Noble apt metadata
selected these versions (the final pinned-snapshot build must recheck them):

| Package/version | Archive SHA256 |
| --- | --- |
| smartmontools 7.4-2build1 | 8859c62e6346dcf0a1db77a3647f75bb7e009fd28750f5fe0f4f5a95e5078f90 |
| libinput-tools 1.25.0-1ubuntu3.7 | 9344c995e618bb745275c6c0643d6abd020984a4017c4dff5223fc1b19287702 |
| evtest 1:1.35-1 | bdee8f0b174f8ed0df8a61ccb8ccd2c1f131e7eb0c8a54f12358fa96127cdf89 |
| pciutils 1:3.10.0-2build1 | f3a2f1237f611258684a4f7789c5b75f4c7f172988feebf990ef593f54bac324 |

Only smartmontools supplied a service/init script; none of these four supplied
a timer, cron job or preset file. Its postinst runs `update-rc.d ... defaults`,
uses `deb-systemd-helper enable` for smartd.service/smartmontools.service, and
requests daemon start. Build-time policy-rc.d blocks the start but cannot prevent
future boot activation. configure-rootfs therefore disables SysV links, disables
both unit names and masks both. The unit's `ConditionVirtualization=no` means a
VM's inactive daemon alone does **not** establish safe physical startup policy.
The shipped update-smart-drivedb helper is not scheduled or invoked by this
change; its postinst `--install` operation installs the bundled drive database.

## Parent-only use

Use an authenticated parent terminal after leaving child use; keep independent
parent escape/recovery available. Do not grant child users input/disk group
membership or loosen device permissions. `libinput list-devices` and event
reads generally need sudo; lspci and help/version queries generally do not.
SMART device reads require sudo. Choose the exact device after inspecting the
local device list; never paste a guessed disk/event number.

Keep traces outside Git, diagnostics bundles, sync media and release artifacts:
`umask 077; trace_dir=$(mktemp -d "$HOME/toddlerbox-diagnostics.XXXXXX")`.
Traces can contain device identities and typed input; do not type passwords or
private content while capturing. Redirections below are made by the parent shell.

- `sudo timeout --kill-after=2s 10s libinput list-devices >"$trace_dir/input-devices.txt"`
- `sudo timeout --kill-after=2s 10s libinput debug-events --device /dev/input/eventN >"$trace_dir/input-events.txt"`
- `sudo timeout --kill-after=2s 10s evtest /dev/input/eventN >"$trace_dir/evtest.txt"`
- `timeout --kill-after=2s 5s lspci -nn >"$trace_dir/pci.txt"`
- `sudo timeout --kill-after=2s 10s smartctl -n standby -a /dev/SELECTED_DISK >"$trace_dir/smart.txt"`

These are explicit bounded read-only queries, with no exclusive grabs. Never add
`--grab`, SMART enable/settings/self-test flags, setpci writes, record/replay or
live database downloads to routine diagnosis. SMART standby avoids waking a
sleeping drive; unsupported bridges/virtual disks may reject queries. smartctl's
exit status is a health/error bitmask, not simply success/failure. Event captures
normally end with timeout status 124. Do not run the interactive alsamixer as an
automated check or alter volume unexpectedly; use the existing parent audio guide
for deliberate audio playback.

## Qualification and delivery limits

`system/check-diagnostic-tools.sh` is an explicit repository-side clean-image
smoke check, not a boot service or installed update payload. In a disposable
image built from the final integrated source, run it from a parent terminal with
`/usr/sbin` on PATH. It checks command paths, package versions, bounded help/version
operations, both masked/inactive SMART units and absent SysV startup links.
Save output privately; retain the complete `/opt/toddlerbox/packages.tsv`, source
identity, builder commands/toolchain and image checksums in final VALIDATION.md.
Also inspect installed package dependencies/units and compare enabled timers and
services against the genuine baseline image: no new automatic monitoring or
network job may appear. Reinspect archive scripts if pinned versions differ.

Then explicitly run the bounded read-only enumeration/event queries above on
synthetic VM devices and verify parent recovery still works. Use a synthetic
SMART target if available; record unsupported virtual-device operations rather
than treating rejection as physical evidence. The shell check performs no audio
playback or real device capture. Physical input devices, SMART passthrough and
audio routing/hearing need the appropriate hardware evidence; this work does not
reopen #19 or request another parent audio acceptance.

No clean image or VM was built/run for this task. Builder qualification, final
package manifest and the integrated image's enabled-unit comparison remain
outstanding. This is prepared source for a future image, not released availability.

Task-local evidence: focused pytest through frozen compatible uv environment
(`/tmp/toddlerbox-053/.venv`, offline, PYTHONPATH=src) passed 8 tests including
existing audio checks and a disposable-root real systemctl enable/disable/mask
check. `bash -n` and `git diff --check` passed. Extracted archive binaries ran
bounded help/version queries for evtest, smartctl and lspci without installation
or hardware access. Noble evtest rejects --help with status 1 and prints USAGE;
the smoke check explicitly validates that behavior. libinput and installed-image
command checks remain for the builder. These are synthetic/source checks only.
