#!/usr/bin/env bash
# Copy beside toddlerbox-installer.iso; run on Linux with: bash flash-installer.sh
set -euo pipefail

# Filled by the image build (and when packaging an already-built ISO).
EXPECTED_SHA256=''

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

check_target() {
    local target=$1 iso_bytes=$2 mounts types
    # lsblk consults the kernel; regular files and partitions cannot pass this.
    [[ $target == /dev/* && $(lsblk -dnro TYPE "$target") == disk ]] ||
        fail 'Choose a whole disk such as /dev/sdb, not a partition or file.'
    [[ $(lsblk -dnro RO "$target") == 0 ]] || fail 'That disk is read-only.'
    [[ $(blockdev --getsize64 "$target") -ge $iso_bytes ]] || fail 'That disk is too small for the ISO.'
    mounts=$(lsblk -nrpo MOUNTPOINTS "$target")
    [[ -z ${mounts//[[:space:]]/} ]] ||
        fail 'That disk has mounted filesystems or active swap. Unmount/eject its volumes first. If it holds this script or ISO, copy both onto the Linux computer first.'
    types=$(lsblk -nro TYPE "$target")
    while IFS= read -r kind; do
        [[ $kind == disk || $kind == part ]] ||
            fail 'That disk has an active device mapping (for example LVM, encryption, or RAID).'
    done <<< "$types"
}

flash() {
    local iso=$1 target=$2 iso_bytes=$3 answer
    target=$(readlink -f -- "$target")
    check_target "$target" "$iso_bytes"
    printf '\nSelected disk:\n'
    lsblk -dpo NAME,SIZE,MODEL,TRAN "$target"
    printf '\nALL DATA ON %s WILL BE ERASED.\n' "$target"
    printf 'Type exactly ERASE %s (or press Enter to cancel): ' "$target"
    IFS= read -r answer || answer=''
    [[ $answer == "ERASE $target" ]] || { printf 'Cancelled; nothing written.\n'; return; }
    # Recheck after the prompt in case a desktop automounted a volume meanwhile.
    check_target "$target" "$iso_bytes"
    printf '\nWriting installer; keep the drive connected...\n'
    dd if="$iso" of="$target" bs=4M conv=fsync status=progress
    blockdev --flushbufs "$target"
    printf '\nVerifying every written byte...\n'
    cmp -n "$iso_bytes" -- "$iso" "$target" || fail 'Read-back verification failed. Do not use this drive.'
    printf '\nDone. The verified installer drive can now be unplugged and booted on the target PC.\n'
    printf 'Use UEFI boot with Secure Boot disabled. The installer will separately confirm erasing the PC disk.\n'
}

main() {
    local script_dir iso iso_bytes actual command target
    [[ $# == 0 ]] || fail 'Run without arguments: bash flash-installer.sh'
    [[ $(uname -s) == Linux ]] || fail 'Run this script on the Linux computer.'
    for command in lsblk blockdev readlink stat sha256sum dd cmp; do
        command -v "$command" >/dev/null || fail "Missing command: $command (requires coreutils and util-linux)."
    done
    script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
    iso="$script_dir/toddlerbox-installer.iso"
    [[ -f $iso && -s $iso ]] || fail "Put toddlerbox-installer.iso beside this script: $script_dir"
    [[ -t 0 ]] || fail 'Run interactively in a terminal.'
    if (( EUID != 0 )); then
        command -v sudo >/dev/null || fail 'Run as root: sudo bash flash-installer.sh'
        exec sudo bash "$script_dir/$(basename -- "${BASH_SOURCE[0]}")"
    fi
    printf 'Checking ISO: %s\n' "$iso"
    actual=$(sha256sum -- "$iso")
    actual=${actual%% *}
    if [[ -n $EXPECTED_SHA256 ]]; then
        [[ $actual == "$EXPECTED_SHA256" ]] || fail 'ISO checksum mismatch; nothing written. Copy the original ISO again.'
        printf 'ISO checksum verified.\n'
    else
        printf 'ISO SHA-256: %s (this source script has no packaged checksum).\n' "$actual"
    fi
    iso_bytes=$(stat -c %s -- "$iso")
    printf '\nAvailable disks and mounted volumes:\n'
    lsblk -p -o NAME,SIZE,MODEL,TRAN,TYPE,MOUNTPOINTS
    printf '\nEnter the whole disk to erase (example /dev/sdb), or Enter to cancel: '
    IFS= read -r target || target=''
    [[ -n $target ]] || { printf 'Cancelled; nothing written.\n'; return; }
    flash "$iso" "$target" "$iso_bytes"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
