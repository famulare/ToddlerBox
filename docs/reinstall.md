# Reinstalling the repaired ToddlerBox image

Use the installer linked in [the current build record](builds/README.md).
Use the release download helper linked there to verify the complete ISO automatically,
then flash with Etcher and let its write validation complete. No manual release-hash
comparison is required.
Choose the USB by its physical identity; the ISO is an installer, and the HP's
installation prompt separately requires confirmation of its exact internal disk.

## Preserve Rosie's new work first

Reinstallation erases the selected internal disk. Before erasing it, leave child
mode, then copy `/var/lib/toddlerbox` to private external storage/the Mac and
verify the copy. That includes Paint current/archives, Typing current/archives
and the photo library. Also preserve `/etc/toddlerbox/config.yaml`,
`/etc/toddlerbox-sync` and `/var/lib/toddlerbox-sync` privately if configured;
they contain credentials, persistent device identity and sync state. Keep that
backup on the Mac before repurposing the only USB as installer media. A backup
left solely on the HP or on the USB about to be flashed is insufficient.

After leaving child mode, a parent terminal can make one private archive:

```sh
sudo tar -czf /home/parent/ToddlerBox-private-backup.tar.gz -C / \
  var/lib/toddlerbox etc/toddlerbox etc/toddlerbox-sync var/lib/toddlerbox-sync
sudo chown parent:parent /home/parent/ToddlerBox-private-backup.tar.gz
chmod 600 /home/parent/ToddlerBox-private-backup.tar.gz
sha256sum /home/parent/ToddlerBox-private-backup.tar.gz
```

Copy it to the Mac and verify that checksum there before flashing/reinstalling.
Stop if tar reports an error. Treat this archive as private credential material.

The original private Drive setup package can provision the new installation,
but its initial photo deposit is not a backup of drawings or typing created
since installation. Do not upload the setup package or backup to public GitHub.

Boot the flashed USB in x86-64 UEFI mode with Secure Boot disabled. Confirm the
installation target, wait for verified installation/shutdown, remove the USB,
and set the new parent password. Import the private setup package in parent
mode as described in [Drive setup](drive-sync.md). Preserve and restore new
creations explicitly before normal use; cloud-to-child creation restoration is
never automatic. If restoring old YAML, retain the new Reading defaults to
make all 75 words available.

## Bounded HP acceptance

In parent GNOME, check visible Wi-Fi networks, connect, resolve a website, then
reboot and confirm reconnection. In child mode, check trackpad light tap and firm
click/drag, touchscreen edges, volume-up/down/mute keys, Reading sound-unit taps
and whole-word reveal, Music playback plus overlapping piano keys and Free Play.
Confirm Home stops sound and Ctrl+Alt+Home still reaches parent login. Record any
remaining failure with the parent controller/session journal. VM qualification
cannot establish the HP's radio, audio routing or physical input behavior.
