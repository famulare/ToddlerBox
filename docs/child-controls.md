# Child input and audio

The first physical run reported working touchscreen input and trackpad movement
with a working physical click, but no tap-to-click. Reading was quiet, Music's
notes moved without audible sound, and neither normal nor Fn media keys adjusted
volume. The intermittent Paint drag stop has not been reproduced.

The child session enables libinput tap-to-click in its own Cage compositor.
The binary is built from Ubuntu's authenticated snapshot Cage source, retaining
Ubuntu patches and its MIT license. Only touchpads with tap capability change;
mouse, touchscreen and parent GNOME policy are untouched. Physical clicks keep
working. GNOME dconf touchpad scripts do not configure standalone Cage.

PipeWire, its PulseAudio compatibility service and WirePlumber are explicit image
packages. The child session starts them with an eight-second bound and selects
SDL's PulseAudio output for both Music and Reading. The independent controller
handles Linux volume-up/down/mute keys while child mode is active: five-percent
steps, up/down unmute, a 100% ceiling, bounded repeats and a two-second subprocess
deadline. Audio commands run as the child account and do not open an overlay.
Parent mode uses GNOME's normal controls. Escape/watchdog processing never waits
for volume commands.

The HP subsequently confirmed working media keys but insufficient loudness.
The pending audio patch changes Music 0.25 → 1.0 and Reading/Math 0.35 → 0.70.
These are signal-gain changes, not guaranteed perceived-loudness multipliers.
No recordings, speech timing, or song dynamics change. Piano keys also gain
headroom-aware amplification and a 600 ms release decay.

Each new child session initializes the selected default sink to
`audio.startup_volume` (default 0.80), then unmutes it. Setup retries for at most
1.5 seconds with a two-second outer deadline; a missing/stalled sink cannot
prevent child-session startup or independent recovery. Activity changes do not
reset volume. Re-entering child mode, including recovery after a crash, restores
the configured startup level. Parent GNOME keeps its own normal controls.

WirePlumber 0.4.17 `wpctl` uses a cubic volume scale: 0.80 corresponds to roughly
0.512 linear gain before hardware calibration. With the new app gains, this
puts default speech near the old unity-master maximum and default songs near
twice their old maximum. The unchanged master ceiling still lets speech reach
about twice and songs four times their old maximum. Physical HP listening and
output-device selection remain necessary.

Updates preserve `/etc/toddlerbox/config.yaml`, including custom gains. After
this patch is installed, choose **11 Apply louder audio defaults** in parent
Setup & Maintenance, or run:

```sh
sudo toddlerbox-maintenance --action audio-defaults
```

This explicit opt-in sets only Music, Reading, Math and startup gains; it retains
other settings and a durable, private original-config backup at
`/var/lib/toddlerbox-system/audio-config-before.yaml`. It requires authenticated
parent mode and refuses unsafe configuration paths. Start a new child session
afterward. Parents can still edit these gains or startup level in the root-owned
configuration. This patch is on a separate review branch; 0.4.0 is unchanged.

## Current appliance release

ToddlerBox 0.4.0 includes tap-to-click and media keys. Use **ToddlerBox Setup & Maintenance**
for later signed public updates; see [updates](updates.md). Hardware acceptance
is still required because a VM has no HP trackpad or speakers.

## Historical repair for an older installation

The simplest route is the [single parent update bundle](updates.md), which
includes the matching compositor and installs the updater for future releases.
No OS reinstall is needed. The developer checkout route remains available:

Use a checked-out revision of this feature and its matching compiled
`toddlerbox-cage` binary. Verify the published binary SHA-256 independently.
Enter parent mode with Ctrl+Alt+Home and save parent desktop work, then run:

```sh
sudo ./scripts/update-child-controls.sh /path/toddlerbox-cage EXPECTED_SHA256
```

The script checks Ubuntu 24.04/x86-64 and the binary hash, installs the audio
packages, checks shared libraries, retains prior root-owned controls in a backup,
and durably replaces the controller/session/helper/compositor. Controller restart
returns to parent login; select Start ToddlerBox there. It does not replace the
app release, `/etc/toddlerbox/config.yaml`, child work or private Drive state.
This is a parent maintenance operation, never a child action.

If audio remains quiet/silent, retain the parent-visible child runtime log and
controller journal; report the selected speaker/headphone/HDMI output. A first
successful hardware check should cover tap versus firm click, drag, volume
up/down/mute, Reading speech and Music, plus parent escape during playback.
