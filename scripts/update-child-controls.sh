#!/bin/bash
# Parent-invoked patch for the qualified Ubuntu 24.04 image; preserves child data.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $EUID == 0 ]] || { echo 'Run with sudo from parent mode.' >&2; exit 1; }
[[ $(cat /run/toddlerbox-system/mode) == parent ]] || { echo 'Enter parent mode first; save parent work before applying.' >&2; exit 1; }
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 24.04 && $(uname -m) == x86_64 ]] || exit 1
binary=${1:?Compiled toddlerbox-cage path required}
expected=${2:?Independently checked Cage SHA-256 required}
[[ $expected =~ ^[a-f0-9]{64}$ && -f $binary ]] || exit 1
[[ $(sha256sum "$binary" | cut -d' ' -f1) == "$expected" ]] || { echo 'Cage checksum mismatch.' >&2; exit 1; }
# Copy verified bytes into root-only staging before package installation/updates.
stage=$(mktemp -d /var/lib/toddlerbox-system/controls-stage.XXXXXX)
trap 'rm -rf "$stage"' EXIT
install -m 0755 "$binary" "$stage/cage"
[[ $(sha256sum "$stage/cage" | cut -d' ' -f1) == "$expected" ]] || exit 1
apt-get update
apt-get install -y --no-install-recommends pipewire pipewire-pulse wireplumber
ldd "$stage/cage" >"$stage/libraries"
! grep -q 'not found' "$stage/libraries"
backup=$(mktemp -d /var/lib/toddlerbox-system/controls-backup.XXXXXX)
for file in /usr/local/lib/toddlerbox-system/controller.py /usr/local/libexec/toddlerbox-session /usr/local/libexec/toddlerbox-volume /usr/local/libexec/toddlerbox-cage; do
    [[ ! -e $file ]] || cp -p "$file" "$backup/$(basename "$file")"
done
replace() {
    install -m "$3" "$1" "$2.controls-new"
    sync -f "$2.controls-new"
    mv -f "$2.controls-new" "$2"
    sync -f "$(dirname "$2")"
}
replace system/controller.py /usr/local/lib/toddlerbox-system/controller.py 0644
replace system/bin/toddlerbox-volume /usr/local/libexec/toddlerbox-volume 0755
replace "$stage/cage" /usr/local/libexec/toddlerbox-cage 0755
replace system/bin/toddlerbox-session /usr/local/libexec/toddlerbox-session 0755
printf 'Controls installed. Backup: %s\nThe controller restart returns to parent login. Start ToddlerBox there.\n' "$backup"
# All durable replacements precede a session restart that can close this terminal.
systemctl restart --no-block toddlerbox-controller.service
