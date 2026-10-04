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

These are corrections to the system configuration. The actual HP output routing
and loudness still need checking; moving notes alone do not prove audible output.
App software gain remains the existing Music 0.25 / Reading 0.35. Increase system
volume with the hardware keys after the patch, and select the intended speakers
in parent Sound settings if necessary. Do not change app gains to hide an
unidentified device-routing issue.

## Current appliance release

ToddlerBox 0.3.0 includes these controls. Use **ToddlerBox Setup & Maintenance**
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
