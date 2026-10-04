# Hardware support boundary

Reference target: the existing HP touchscreen laptop; x86-64 Ubuntu 24.04 LTS,
UEFI, Secure Boot disabled for the current unsigned installer. A VM qualifies
system behavior, not the physical radio, touchscreen firmware or speaker wiring.

The package recipe deliberately uses explicit packages with no implicit apt
recommendations. Its supported hardware paths are:

| Function | Included Ubuntu components |
| --- | --- |
| Kernel/devices/firmware | linux-generic, linux-firmware, initramfs MODULES=most, udev/systemd |
| Wi-Fi/network | NetworkManager/GNOME settings, wpasupplicant, iw, rfkill |
| Touch/trackpad | kernel HID/input, wlroots/libinput via standalone Cage; scoped tap-to-click patch |
| Graphics | Ubuntu kernel DRM, Mesa/EGL, GNOME parent session and Cage child session |
| Sound | ALSA libraries, PipeWire/Pulse compatibility and WirePlumber in child user session |
| Removable storage | udisks2, GVFS backends, Nautilus and filesystem tools |
| Power | logind, upower, power-profiles-daemon; child-only session inhibitors |

The HP's prior missing Wi-Fi backend is explicitly included. GNOME desktop
dependencies in `desktop-extras.txt` remain intact. No system-wide keyboard remap
or nested GNOME child session is introduced. Parent mode has normal controls.
Do not remove a hardware/service package to shrink the child UI.

Printing/scanning, Bluetooth peripherals, arbitrary GPU drivers, Secure Boot and
other machines are not physically certified by this release. Add evidence and
required Ubuntu packages before claiming those functions. Keep the actual dpkg
manifest with each release; LTS maintenance uses signed Ubuntu updates separately
from the pinned build snapshot.

After generic VM qualification, collect a reviewed HP report and test repeated
boots, Wi-Fi scan/connect/reconnect, sound and volume keys, trackpad taps/clicks,
touch edges/multiple fingers/drag, independent escape during a freeze,
sleep/resume and one parent update/rollback. CPU/RAM/display/UEFI details can tune
the VM; radio and touch hardware still require that physical checklist.
