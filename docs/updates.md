# Updates without reinstalling Ubuntu

ToddlerBox updates are explicit parent maintenance. Download one public update
bundle and check its SHA-256 against the release page. No weekly checks,
background downloads, or child-facing update controls run on the laptop.

## First update on the existing HP installation

An executable `.pyz` bundle includes its bootstrap updater, so no Git checkout,
developer tools, or Python dependency installation is needed. Enter parent mode
with Ctrl+Alt+Home and save parent desktop work. In the download directory:

```sh
sha256sum ToddlerBox-update.pyz
# Compare the result with the independently published release checksum BEFORE sudo.
sudo /usr/bin/python3 ToddlerBox-update.pyz --sha256 EXPECTED_SHA256
```

The updater requires Ubuntu 24.04 x86-64 and parent mode. It verifies the open
bundle and every payload checksum, stages private copies, checks available disk
space and compositor libraries, and keeps the previous system files. The first
controls update installs PipeWire packages through Ubuntu's signed repositories;
this step needs networking. Apt failure stops before application/system file
replacement. Save parent work first: restarting the controller can return to the
parent login screen. Log in and select **Start ToddlerBox** after installation.

## Later updates and rollback

The first update installs a root-owned command for subsequent bundles:

```sh
sudo toddlerbox-update /path/ToddlerBox-update.pyz EXPECTED_SHA256
sudo toddlerbox-update --rollback
```

Rollback restores the previous controller/session/compositor and, if included,
the app's previous release links. It leaves newly installed Ubuntu audio packages
in place. Rolling back the first update also removes its newly installed updater
command; the verified bootstrap bundle remains usable. Repeating the same
successful bundle is a no-op and keeps its rollback
backup. Backups and a durable update journal live in
`/var/lib/toddlerbox-system/updates`; they are not automatically pruned.

The updater cannot atomically commit several system files across a power cut.
Its journal records an incomplete update before replacement starts. If power is
lost during an update, use the parent boot recovery route, then explicitly roll
back before retrying. If that interrupted update never installed the command, use
the independently verified bootstrap bundle:

```sh
sudo /usr/bin/python3 ToddlerBox-update.pyz --rollback
```

An ordinary failed replacement attempts rollback immediately. Corrupt backups
are refused before any files are restored. This is a maintenance patch mechanism,
not an Ubuntu release upgrade or a whole-disk snapshot. The qualified USB image
remains the OS recovery option.

## What updates preserve

Updates never replace `/var/lib/toddlerbox`, `/etc/toddlerbox/config.yaml`, Drive
credentials, the device UUID, or sync history/state. Rosie’s photos, drawings and
Typing documents stay in place. The bundle format allows only fixed system
destinations; downloaded bundles cannot name arbitrary installation paths or
commands. App bundles use the existing release installer, which verifies data
schema compatibility and keeps previous releases. Backup child work separately
before maintenance, as with other computer updates.

The initial hardware-controls bundle contains only system changes. Future app
changes can be included in the same download. A desktop button/file picker can
be added later; the current interface is one parent command.

## Build a bundle

Use the pinned Ubuntu Cage build described in `VALIDATION.md`, then:

```sh
uv run --no-project --python /usr/bin/python3 system/build-update.py \
  --cage build/child-controls-qa/toddlerbox-cage \
  --output build/ToddlerBox-update.pyz
# Optional: --app build/toddlerbox-app-<id>.tar.gz
```

The optional app archive must use the same Ubuntu/Python ABI as the installation;
this command packages an existing release archive, it does not build one. The
output has SHA-256 and source-identity sidecars. Fixed ZIP timestamps/order make
identical inputs repeatable. Publish the checksum independently of the downloaded
executable and never include private setup packages or family data.
