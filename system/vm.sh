#!/bin/bash
# Uses an overlay: destroying a test VM never changes the built system disk.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build/vm
action=${1:-start}
firmware=OVMF_VARS.fd
if [[ "$action" == installer || "$action" == installed ]]; then
    firmware=INSTALL_OVMF_VARS.fd
fi
case "$action" in
    start|installer|installed)
        if docker inspect toddlerbox-vm >/dev/null 2>&1; then
            echo 'A toddlerbox-vm container already exists; stop it before restarting.' >&2
            exit 1
        fi
        if [[ "$action" == installer && -e build/vm/install-target.qcow2 ]]; then
            echo 'Installation target already exists; preserve or remove it explicitly before a fresh install.' >&2
            exit 1
        fi
        if [[ "$action" == installed && ! -e build/vm/install-target.qcow2 ]]; then
            echo 'No installed VM target exists.' >&2
            exit 1
        fi
        docker run --rm -e "VM_UID=$(id -u)" -e "VM_GID=$(id -g)" \
            -e "VM_FIRMWARE=$firmware" -e "VM_ACTION=$action" \
            -v "$PWD/build:/build" toddlerbox-image-tools bash -c '
            if [[ "$VM_ACTION" == installer || ! -f "/build/vm/$VM_FIRMWARE" ]]; then
                cp /usr/share/OVMF/OVMF_VARS_4M.fd "/build/vm/$VM_FIRMWARE"
            fi
            if [[ ! -f /build/vm/disk.qcow2 ]]; then
                qemu-img create -f qcow2 -F qcow2 -b /build/toddlerbox.qcow2 /build/vm/disk.qcow2
            fi
            chown -R "$VM_UID:$VM_GID" /build/vm'
        devices=()
        accel=(-accel tcg,thread=multi)
        cpu_model=qemu64
        if [[ -c /dev/kvm && -r /dev/kvm && -w /dev/kvm ]]; then
            devices=(--device /dev/kvm)
            accel=(-accel kvm)
            cpu_model=host
        fi
        media=()
        if [[ "$action" == installer ]]; then
            # Separate empty installation target, never the validated base image.
            docker run --rm -v "$PWD/build:/build" toddlerbox-image-tools \
                qemu-img create -f qcow2 /build/vm/install-target.qcow2 16G
            docker run --rm -v "$PWD/build:/build" toddlerbox-image-tools \
                chown "$(id -u):$(id -g)" /build/vm/install-target.qcow2
            media=(-cdrom /build/toddlerbox-installer.iso -boot d)
            disk=install-target.qcow2
        elif [[ "$action" == installed ]]; then
            disk=install-target.qcow2
        else
            disk=disk.qcow2
        fi
        docker run -d --name toddlerbox-vm --user "$(id -u):$(id -g)" "${devices[@]}" --network=none \
            -v "$PWD/build:/build" toddlerbox-image-tools \
            qemu-system-x86_64 "${accel[@]}" -machine q35 -cpu "$cpu_model" -smp 2 -m 4096 \
            -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
            -drive "if=pflash,format=raw,file=/build/vm/$firmware" \
            -drive "if=virtio,format=qcow2,discard=unmap,detect-zeroes=unmap,file=/build/vm/$disk" \
            -device virtio-vga -device qemu-xhci -device usb-tablet -nic none \
            -display none -vnc unix:/build/vm/vnc.sock \
            -qmp unix:/build/vm/qmp.sock,server=on,wait=off \
            -chardev socket,id=serial,path=/build/vm/serial.sock,server=on,wait=off,logfile=/build/vm/serial.log \
            -serial chardev:serial "${media[@]}"
        ;;
    stop) docker stop --timeout 15 toddlerbox-vm; docker rm toddlerbox-vm ;;
    *) echo 'Usage: system/vm.sh start|installer|installed|stop' >&2; exit 2 ;;
esac
