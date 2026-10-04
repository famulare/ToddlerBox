#!/bin/bash
# Runs only inside the image assembly container, never on the development host.
set -euo pipefail
[[ -r /source/system/versions.env && -x /run/uv && $EUID == 0 ]] || { echo 'Image assembly container required' >&2; exit 1; }
release_id=$1
source_dir=/usr/local/share/toddlerbox-build
install -d /etc/toddlerbox /usr/local/lib/toddlerbox-system /usr/local/libexec
install -d -m 0700 /var/lib/toddlerbox-system
install -m 0644 "$source_dir/controller.py" /usr/local/lib/toddlerbox-system/controller.py
install -m 0644 "$source_dir/update_bundle.py" /usr/local/lib/toddlerbox-system/update_bundle.py
install -m 0644 "$source_dir/boot_recovery.py" "$source_dir/appliance.py" "$source_dir/release_client.py" /usr/local/lib/toddlerbox-system/
install -m 0644 "$source_dir/release-public-key.pem" /etc/toddlerbox/
install -D -m 0755 "$source_dir/grub-parent-recovery" /etc/grub.d/41_toddlerbox_parent
install -d /etc/default/grub.d
printf 'GRUB_TIMEOUT_STYLE=menu\nGRUB_TIMEOUT=5\nGRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX_DEFAULT=""\nGRUB_CMDLINE_LINUX="console=tty0 console=ttyS0,115200"\n' >/etc/default/grub.d/toddlerbox.cfg
install -m 0755 "$source_dir/bin/toddlerbox-maintenance" /usr/local/sbin/
touch /var/lib/toddlerbox-system/appliance-v1
printf '{"sequence":%s,"source":"%s"}\n' "$(cat "$source_dir/release-sequence")" "$release_id" >/var/lib/toddlerbox-system/release-sequence.json
chmod 0600 /var/lib/toddlerbox-system/release-sequence.json
install -d -m 0700 /var/lib/toddlerbox-system/updates
install -m 0755 "$source_dir/bin/toddlerbox-update" /usr/local/sbin/
install -d /usr/local/lib/toddlerbox-system/tbx_sync
install -m 0644 "$source_dir"/tbx_sync/*.py /usr/local/lib/toddlerbox-system/tbx_sync/
install -m 0644 /source/src/toddlerbox/runtime/image_safety.py /usr/local/lib/toddlerbox-system/tbx_sync/image_safety.py
install -m 0755 "$source_dir/bin/toddlerbox-sync" /usr/local/sbin/
install -m 0755 "$source_dir/bin/toddlerbox-sync-worker" /usr/local/libexec/
install -d -m 0700 /etc/toddlerbox-sync /var/lib/toddlerbox-sync
install -m 0755 "$source_dir/bin/toddlerbox-mode" "$source_dir/bin/toddlerbox-firstboot" "$source_dir/bin/toddlerbox-install-release" /usr/local/sbin/
install -m 0755 "$source_dir/bin/toddlerbox-volume" /usr/local/libexec/
install -m 0755 "$source_dir/bin/toddlerbox-session" /usr/local/libexec/
install -m 0644 "$source_dir"/units/* /etc/systemd/system/
ln -s "releases/$release_id" /opt/toddlerbox/current
chmod -R a+rX /opt/toddlerbox/releases
cp /opt/toddlerbox/current/config.yaml /etc/toddlerbox/config.yaml
sed -i 's|data_root: ./data|data_root: /var/lib/toddlerbox|' /etc/toddlerbox/config.yaml
printf '\ntyping:\n  autosave_seconds: 5\n' >>/etc/toddlerbox/config.yaml
if getent passwd ubuntu >/dev/null; then
    userdel --remove ubuntu
fi
useradd --create-home --shell /bin/bash parent
usermod -aG sudo,adm parent
# Passwords are set on first boot. Child cannot authenticate or administer the OS.
useradd --create-home --shell /bin/bash toddlerbox
passwd -l parent
passwd -l toddlerbox
install -d -o toddlerbox -g toddlerbox -m 0700 /var/lib/toddlerbox
install -d -o toddlerbox -g toddlerbox -m 0755 /var/lib/toddlerbox/photos /var/lib/toddlerbox/photos/library /var/lib/toddlerbox/photos/thumbs
install -d /var/lib/AccountsService/users /usr/share/wayland-sessions
cat >/var/lib/AccountsService/users/toddlerbox <<'EOF'
[User]
Session=toddlerbox
XSession=toddlerbox
SystemAccount=true
EOF
cat >/var/lib/AccountsService/users/parent <<'EOF'
[User]
Session=ubuntu
XSession=ubuntu
SystemAccount=false
EOF
cat >/usr/share/wayland-sessions/toddlerbox.desktop <<'EOF'
[Desktop Entry]
Name=ToddlerBox
Comment=Standalone child session
Exec=/usr/local/libexec/toddlerbox-session
Type=Application
DesktopNames=Cage
EOF
cat >/usr/share/applications/toddlerbox-child.desktop <<'EOF'
[Desktop Entry]
Name=Start ToddlerBox
Comment=Save your parent work before switching to the child session
Exec=pkexec /usr/local/sbin/toddlerbox-mode child
Type=Application
Icon=applications-games
Categories=System;
EOF
cat >/usr/share/applications/toddlerbox-maintenance.desktop <<'EOF'
[Desktop Entry]
Name=ToddlerBox Setup & Maintenance
Exec=/usr/local/sbin/toddlerbox-maintenance
Terminal=true
Type=Application
Icon=preferences-system
Categories=System;
EOF
install -d -o parent -g parent /home/parent/.config /home/parent/.config/autostart
cat >/home/parent/.config/autostart/toddlerbox-setup.desktop <<'EOF'
[Desktop Entry]
Name=ToddlerBox First Setup
Exec=gnome-terminal -- /usr/local/sbin/toddlerbox-maintenance --first-run
Type=Application
OnlyShowIn=GNOME;
EOF
chown parent:parent /home/parent/.config/autostart/toddlerbox-setup.desktop
for command in setup run status reconnect; do
    case "$command" in
        setup) title='Set Up ToddlerBox Drive' ;;
        run) title='Sync ToddlerBox Now' ;;
        status) title='ToddlerBox Sync Status' ;;
        reconnect) title='Reconnect ToddlerBox Drive' ;;
    esac
    cat >"/usr/share/applications/toddlerbox-sync-$command.desktop" <<EOF
[Desktop Entry]
Name=$title
Exec=pkexec /usr/local/sbin/toddlerbox-sync $command
Terminal=true
Type=Application
Icon=folder-remote
Categories=System;
EOF
done
cat >/etc/polkit-1/rules.d/49-toddlerbox-inhibit.rules <<'EOF'
polkit.addRule(function(action, subject) {
    if (subject.user == "toddlerbox" &&
        ["org.freedesktop.login1.inhibit-handle-power-key",
         "org.freedesktop.login1.inhibit-handle-suspend-key",
         "org.freedesktop.login1.inhibit-handle-hibernate-key",
         "org.freedesktop.login1.inhibit-handle-lid-switch"].indexOf(action.id) >= 0)
        return polkit.Result.YES;
});
EOF
# GDM reads a root-owned tmpfs config; disk-full cannot prevent parent recovery.
rm -f /etc/gdm3/custom.conf
ln -s /run/toddlerbox-system/gdm.conf /etc/gdm3/custom.conf
install -d /etc/systemd/system/gdm3.service.d
cat >/etc/systemd/system/gdm3.service.d/toddlerbox.conf <<'EOF'
[Unit]
Wants=toddlerbox-controller.service
After=toddlerbox-controller.service toddlerbox-firstboot.service toddlerbox-bootgate.service

[Service]
TimeoutStopSec=10
EOF
systemctl enable toddlerbox-bootgate.service toddlerbox-firstboot.service toddlerbox-controller.service NetworkManager.service
systemctl enable gdm3.service
systemctl set-default graphical.target
systemctl mask ctrl-alt-del.target
install -d /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\nSystemMaxUse=100M\nSystemKeepFree=500M\n' >/etc/systemd/journald.conf.d/toddlerbox.conf
install -d /etc/NetworkManager/conf.d
printf '[main]\nplugins=keyfile\n' >/etc/NetworkManager/conf.d/toddlerbox.conf
echo toddlerbox >/etc/hostname
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
ln -s /etc/machine-id /var/lib/dbus/machine-id
# No build identity or network proxy is installed in the final filesystem.
rm -f /usr/sbin/policy-rc.d
printf 'MODULES=most\nCOMPRESS=zstd\n' >/etc/initramfs-tools/conf.d/toddlerbox
printf 'virtio_gpu\nvirtio_blk\nvirtio_pci\n' >>/etc/initramfs-tools/modules
install -m 0755 "$source_dir/initramfs/hook" /etc/initramfs-tools/hooks/toddlerbox-installer
install -m 0755 "$source_dir/initramfs/install" /etc/initramfs-tools/scripts/init-premount/toddlerbox-install
update-initramfs -u -k all
dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' >/opt/toddlerbox/packages.tsv
cp "$source_dir/versions.env" /opt/toddlerbox/versions.env
# Builds use a pinned snapshot; installed parent maintenance uses signed live LTS repositories.
cp /etc/apt/sources.list.d/ubuntu.sources /opt/toddlerbox/build-ubuntu.sources
printf 'Types: deb\nURIs: https://archive.ubuntu.com/ubuntu/\nSuites: noble noble-updates\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n\nTypes: deb\nURIs: https://security.ubuntu.com/ubuntu/\nSuites: noble-security\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n' >/etc/apt/sources.list.d/ubuntu.sources
printf 'APT::Periodic::Enable "0";\nAPT::Periodic::Update-Package-Lists "0";\nAPT::Periodic::Unattended-Upgrade "0";\n' >/etc/apt/apt.conf.d/99toddlerbox-explicit-maintenance
systemctl mask apt-daily.timer apt-daily-upgrade.timer
printf '%s\n' "$release_id" >/opt/toddlerbox/release-id
rm -f /var/lib/systemd/random-seed
