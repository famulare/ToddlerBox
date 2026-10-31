#!/bin/bash
# Explicit clean-image qualification, run from an authenticated parent terminal.
# No device capture, playback, disk tests, network access or package installation.
set -euo pipefail
for command in libinput evtest smartctl lspci speaker-test aplay alsamixer pactl paplay pw-play; do
    command -v "$command"
done
for package in libinput-tools evtest smartmontools pciutils alsa-utils pulseaudio-utils pipewire; do
    dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' "$package"
done
# Every subprocess is bounded; help/version checks avoid hardware side effects.
timeout --kill-after=2s 5s libinput --version
timeout --kill-after=2s 5s libinput list-devices --help
timeout --kill-after=2s 5s libinput debug-events --help
# Noble evtest 1.35 has no --help option: it prints usage and exits 1.
evtest_status=0
evtest_help=$(timeout --kill-after=2s 5s evtest --help 2>&1) || evtest_status=$?
printf '%s\n' "$evtest_help"
[[ "$evtest_status" == 1 && "$evtest_help" == *USAGE:* ]]
timeout --kill-after=2s 5s smartctl --version
timeout --kill-after=2s 5s lspci --version
timeout --kill-after=2s 5s speaker-test --help
timeout --kill-after=2s 5s aplay --version
timeout --kill-after=2s 5s alsamixer --help
timeout --kill-after=2s 5s pactl --version
timeout --kill-after=2s 5s paplay --version
timeout --kill-after=2s 5s pw-play --version
for unit in smartmontools.service smartd.service; do
    state=$(systemctl is-enabled "$unit" 2>/dev/null || true)
    [[ "$state" == masked ]] || { echo "$unit: expected masked, got $state" >&2; exit 1; }
    if systemctl is-active --quiet "$unit"; then
        echo "$unit: unexpectedly active" >&2
        exit 1
    fi
done
if compgen -G '/etc/rc[2345].d/S*smartmontools' >/dev/null; then
    echo 'SMART SysV startup unexpectedly enabled' >&2
    exit 1
fi
