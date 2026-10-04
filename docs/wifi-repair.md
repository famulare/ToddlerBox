# Historical offline Wi-Fi repair

ToddlerBox 0.3.0 already includes this backend; use parent setup on a fresh install.
These commands are retained for an earlier installation with no working network.
They are not part of current installation or routine updates.

The HP kernel log shows an Intel Dual Band Wireless AC 3165, loaded `iwlwifi`
firmware and interface `wlo1`. NetworkManager reports the Wi-Fi interface as
unavailable. The installer package record confirms that both `wpasupplicant`
and `iwd` are absent. The image used `--no-install-recommends` and omitted its
Wi-Fi connection backend; driver/firmware are present. This is a confirmed image
omission and a likely cause of the symptom, pending the actual HP repair result.

This omission can be repaired without reinstalling. On the internet-connected Mac, run without sudo:

```sh
curl -fL https://raw.githubusercontent.com/famulare/ToddlerBox/main/scripts/download-wifi-repair.sh -o download-wifi-repair.sh
bash download-wifi-repair.sh
```

Copy the resulting `ToddlerBox-wifi-repair` folder onto another writable USB
stick; keep the installer USB intact. On the HP, open this folder in Files,
right-click and choose Open in Terminal. Run:

```sh
sha256sum -c SHA256SUMS
# Check all five say OK before installing.
sudo dpkg -i ./libnl-3-200_3.7.0-0.3build1.1_amd64.deb ./libnl-genl-3-200_3.7.0-0.3build1.1_amd64.deb ./libnl-route-3-200_3.7.0-0.3build1.1_amd64.deb ./libpcsclite1_2.0.3-1build1_amd64.deb ./wpasupplicant_2.10-21ubuntu0.4_amd64.deb
# Stop and report errors if dpkg fails; otherwise:
sudo systemctl restart NetworkManager
nmcli radio wifi on
nmcli device wifi list --rescan yes
```

Choose the network in the parent desktop. These five Ubuntu packages total
1,750,228 bytes and include the four missing library dependencies. The remainder
of the dependency closure is present in the qualified image's package record.
URLs and SHA-256 values come from its authenticated Ubuntu snapshot metadata;
the Mac helper checks downloaded bytes before reporting success. Do not continue
installation on checksum or dependency failure. No private family data or Google
credentials are part of this repair.

The build recipe now explicitly includes `wpasupplicant`, and future combined
updates install it through the signed Ubuntu package manager. The existing public
controls bundle is unchanged; install the offline Wi-Fi repair first, then that
bundle can download its audio packages. The old qualified installer remains
unchanged and requires this repair on fresh Wi-Fi-only installations.

The newly rebuilt Reading/piano installer includes this backend and `iw`/`rfkill`.
Its fresh installed VM activates `fi.w1.wpa_supplicant1` successfully; physical HP
scanning/association/reconnection remain acceptance checks. See [builds](builds/README.md).
