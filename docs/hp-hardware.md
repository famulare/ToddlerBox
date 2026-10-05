# HP hardware qualification profile

Observed from parent-terminal screenshots supplied on 2026-10-04. Raw uploads
are private inspection material, excluded from source and release artifacts.

| Component | Observed detail |
| --- | --- |
| Product | HP Pavilion x360 m3 Convertible |
| Architecture/kernel | x86-64, Ubuntu 6.8.0-142-generic |
| Memory | 5.7 GiB reported usable; no swap active |
| Panel | 1366 × 768 preferred/current, approximately 60 Hz |
| Storage | Approximately 500 GB Toshiba MQ01ABF050 SATA disk |
| Keyboard | AT Translated Set 2, plus HP WMI hotkeys |
| Touchscreen | ELAN0732:00, vendor/product 04F3:28A2, I²C input devices |
| Trackpad | ETPS/2 Elantech Touchpad |
| Audio | Intel PCH HDA, analog/HDMI output devices present |

The earlier Wi-Fi screenshot identifies Intel Dual Band Wireless-AC 3165 with
iwlwifi firmware loaded. That is separate evidence from this upload; a loaded
driver does not establish successful scanning or connectivity.

CPU model, GPU PCI ID, BIOS revision and exact audio codec remain unobserved:
`lspci` and `lsusb` were unavailable. Displayed kernel or disk paths must never
be used as a later destructive-install target without a fresh physical check.

For closer VM coverage, use 1366 × 768 rendering and a roughly 6 GiB guest;
the existing 4 GiB qualification is a conservative memory case. Q35/UEFI,
virtual HDA and PS/2 keyboard/pointer exercise boot, routing and recovery.
QEMU does not reproduce this Elan touchscreen, Elantech gestures, Intel radio,
panel timing, firmware or aging SATA disk. USB tablet pointer tests are not
physical multi-touch qualification. Keep the generic reproducible VM alongside
this profile, rather than describing either as an HP emulator.

On the HP, verify Wi-Fi scan/connect/reconnect, trackpad tap/physical click,
touchscreen edges and multiple fingers, volume keys/speaker sound, parent escape
and sleep/resume. See [reinstallation acceptance](reinstall.md).
