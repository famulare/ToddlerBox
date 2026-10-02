#!/bin/bash
# Run by build.sh in the image-tools container. No loop mounts or host disks.
set -euo pipefail
cd /build
source /source/system/versions.env
root_uuid=d1952deb-9efc-4225-bc81-2d6af4e7b644
test -d rootfs/boot
rm -f rootfs/.dockerenv rootfs/.containerenv
find rootfs/run -mindepth 1 -delete
echo toddlerbox >rootfs/etc/hostname
chmod -R a+rX rootfs/opt/toddlerbox/releases
printf '127.0.0.1 localhost\n127.0.1.1 toddlerbox\n::1 localhost ip6-localhost\n' >rootfs/etc/hosts
rm -f rootfs/etc/resolv.conf
ln -s /run/NetworkManager/resolv.conf rootfs/etc/resolv.conf
kernel=$(basename "$(ls rootfs/boot/vmlinuz-* | sort -V | tail -1)")
kernel_version=${kernel#vmlinuz-}
mkdir -p rootfs/boot/grub rootfs/boot/efi
cat >rootfs/etc/fstab <<EOF
UUID=$root_uuid / ext4 defaults,errors=remount-ro 0 1
LABEL=TBX_EFI /boot/efi vfat umask=0077 0 2
EOF
cat >rootfs/boot/grub/grub.cfg <<EOF
set timeout=5
set default=0
serial --unit=0 --speed=115200
terminal_input console serial
terminal_output console serial
search --no-floppy --fs-uuid --set=root $root_uuid
menuentry 'ToddlerBox' {
    linux /boot/$kernel root=UUID=$root_uuid rw console=tty0 console=ttyS0,115200
    initrd /boot/initrd.img-$kernel_version
}
menuentry 'Parent recovery — Ubuntu GNOME login' {
    linux /boot/$kernel root=UUID=$root_uuid rw console=tty0 console=ttyS0,115200 toddlerbox.parent=1
    initrd /boot/initrd.img-$kernel_version
}
EOF
# UEFI removable-media fallback works in OVMF and on PCs without an NVRAM entry.
rm -f esp.img root.img toddlerbox.img
truncate -s 256M esp.img
mkfs.vfat -n TBX_EFI -i 54425831 esp.img
mmd -i esp.img ::/EFI ::/EFI/BOOT ::/EFI/ubuntu
mcopy -i esp.img rootfs/usr/lib/shim/shimx64.efi.signed.latest ::/EFI/BOOT/BOOTX64.EFI
mcopy -i esp.img rootfs/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed ::/EFI/BOOT/grubx64.efi
cat >efi-grub.cfg <<EOF
search --no-floppy --fs-uuid --set=root $root_uuid
set prefix=(\$root)/boot/grub
configfile \$prefix/grub.cfg
EOF
mcopy -i esp.img efi-grub.cfg ::/EFI/ubuntu/grub.cfg
mcopy -i esp.img efi-grub.cfg ::/EFI/BOOT/grub.cfg
disk_bytes=$((DISK_MIB * 1024 * 1024))
root_sectors=$((disk_bytes / 512 - 34 - 526336))
truncate -s "$((root_sectors * 512))" root.img
mkfs.ext4 -F -q -L toddlerbox -U "$root_uuid" -m 2 -d rootfs root.img
e2fsck -fn root.img
truncate -s "$disk_bytes" toddlerbox.img
sgdisk --clear --new=1:2048:+256M --typecode=1:ef00 --change-name=1:EFI \
    --new=2:0:0 --typecode=2:8300 --change-name=2:ToddlerBox toddlerbox.img
dd if=esp.img of=toddlerbox.img bs=1M seek=1 conv=notrunc,sparse status=none
dd if=root.img of=toddlerbox.img bs=1M seek=257 conv=notrunc,sparse status=none
rm -f root.img esp.img
qemu-img convert -f raw -O qcow2 -c toddlerbox.img toddlerbox.qcow2
qemu-img compare -f raw -F qcow2 toddlerbox.img toddlerbox.qcow2
mkdir -p iso/boot/grub
cp "rootfs/boot/$kernel" iso/boot/vmlinuz
cp "rootfs/boot/initrd.img-$kernel_version" iso/boot/initrd
zstd -T2 -3 -f toddlerbox.img -o iso/toddlerbox.img.zst
(cd iso && sha256sum toddlerbox.img.zst >toddlerbox.img.zst.sha256)
printf '%s\n' "$disk_bytes" >iso/image-bytes
cat >iso/boot/grub/grub.cfg <<'EOF'
set timeout=-1
menuentry 'Install ToddlerBox — requires disk erase confirmation' {
    linux /boot/vmlinuz toddlerbox.install=1 console=tty0
    initrd /boot/initrd
}
menuentry 'Install ToddlerBox — VM serial console' {
    linux /boot/vmlinuz toddlerbox.install=1 console=tty0 console=ttyS0,115200
    initrd /boot/initrd
}
menuentry 'Power off' { halt }
EOF
grub-mkrescue -o toddlerbox-installer.iso -volid TODDLERBOX iso
cp rootfs/opt/toddlerbox/packages.tsv packages.tsv
cp rootfs/opt/toddlerbox/release-id release-id
release_id=$(cat release-id)
tar -czf "toddlerbox-app-$release_id.tar.gz" -C rootfs/opt/toddlerbox/releases "$release_id"
sha256sum "toddlerbox-app-$release_id.tar.gz" >APP-SHA256SUMS
sha256sum toddlerbox.img toddlerbox.qcow2 toddlerbox-installer.iso >SHA256SUMS
chmod a+r toddlerbox.img toddlerbox.qcow2 toddlerbox-installer.iso SHA256SUMS APP-SHA256SUMS packages.tsv release-id
echo 'Created toddlerbox.qcow2, toddlerbox.img, and toddlerbox-installer.iso'
