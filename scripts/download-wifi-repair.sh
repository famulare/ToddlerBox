#!/bin/bash
# Run on the network-connected Mac (or Linux PC), WITHOUT sudo.
# Ubuntu packages/hashes from authenticated snapshot 20260926T000000Z.
set -euo pipefail
mkdir -p ToddlerBox-wifi-repair
cd ToddlerBox-wifi-repair
cat > SHA256SUMS <<'EOF'
342dcbd9eca155540a556c18862b7900fbdf23363f2b6f2922c00f69a749dd59  wpasupplicant_2.10-21ubuntu0.4_amd64.deb
15b3f61db753dc3db6f62f4259f8b822299343e500886776486612a13a2ed247  libnl-3-200_3.7.0-0.3build1.1_amd64.deb
9ca0cb63f295d00e6346b9924278c07cfc61311cbd288b805b06e25aa08c9fd8  libnl-genl-3-200_3.7.0-0.3build1.1_amd64.deb
c9dbd29cb7fdcf1a0587726cbc5432a7d3e81242108dfcfa2dd6716c44c74d4d  libnl-route-3-200_3.7.0-0.3build1.1_amd64.deb
703bacc9204a7ecc24486ac8c96d15d0b9e2c91c385388e132ad4fd8f56f035a  libpcsclite1_2.0.3-1build1_amd64.deb
EOF
for package in \
  w/wpa/wpasupplicant_2.10-21ubuntu0.4_amd64.deb \
  libn/libnl3/libnl-3-200_3.7.0-0.3build1.1_amd64.deb \
  libn/libnl3/libnl-genl-3-200_3.7.0-0.3build1.1_amd64.deb \
  libn/libnl3/libnl-route-3-200_3.7.0-0.3build1.1_amd64.deb \
  p/pcsc-lite/libpcsclite1_2.0.3-1build1_amd64.deb; do
    name=${package##*/}
    curl -fL --retry 2 --connect-timeout 20 --max-time 180 \
      "https://snapshot.ubuntu.com/ubuntu/20260926T000000Z/pool/main/$package" -o "$name"
done
if command -v sha256sum >/dev/null; then
    sha256sum -c SHA256SUMS
else
    shasum -a 256 -c SHA256SUMS
fi
cat > INSTALL.txt <<'EOF'
Copy this whole folder to the HP using a separate writable USB stick.
In the HP parent terminal, cd into this folder and run:

sha256sum -c SHA256SUMS
# All five must report OK before continuing.
sudo dpkg -i ./libnl-3-200_3.7.0-0.3build1.1_amd64.deb ./libnl-genl-3-200_3.7.0-0.3build1.1_amd64.deb ./libnl-route-3-200_3.7.0-0.3build1.1_amd64.deb ./libpcsclite1_2.0.3-1build1_amd64.deb ./wpasupplicant_2.10-21ubuntu0.4_amd64.deb
# Continue only if dpkg finished successfully (no missing dependencies).
sudo systemctl restart NetworkManager
nmcli radio wifi on
nmcli device wifi list --rescan yes

Select your Wi-Fi in the parent desktop. Do not reformat the ToddlerBox installer
USB; use another writable USB stick. These packages match Ubuntu 24.04 x86-64.
No child work, private configuration, app release, or OS partition is replaced.
EOF
printf 'Verified offline repair downloaded to: %s\nCopy this folder to the HP; follow INSTALL.txt.\n' "$PWD"
