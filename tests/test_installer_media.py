"""Run the real initramfs installer with simulated hybrid-USB/optical media.

Only runtime paths are redirected into the fixture; discovery logic is unchanged.
The checksum command deliberately fails, so no test reaches disk selection/write.
"""
import os
from pathlib import Path
import shlex
import subprocess

import pytest


INSTALLER = Path(os.environ.get(
    "TODDLERBOX_INSTALLER_TEST_SOURCE",
    str(Path(__file__).parents[1] / "system/initramfs/install"),
))


def simulate_media(tmp_path, scenario, installer=INSTALLER):
    tools = tmp_path / "tools"
    tools.mkdir()
    log = tmp_path / "calls"
    console = tmp_path / "console"
    cmdline = tmp_path / "cmdline"
    cmdline.write_text("BOOT_IMAGE=/boot/vmlinuz toddlerbox.install=1 console=tty0\n")
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    mocks = {
        "modprobe": "exit 0",
        "udevadm": "exit 0",
        "sleep": "exit 0",
        "blkid": r'''
case "$*" in
    '-L TODDLERBOX')
        case $SCENARIO in optical) echo /dev/sr0;; *) echo /dev/sdb3;; esac ;;
    '-c /dev/null -t TYPE=iso9660 -o device')
        case $SCENARIO in
            optical) echo /dev/sr0 ;;
            wrong_label) echo /dev/sdc ;;
            missing) : ;;
            *) echo /dev/sdb ;;
        esac ;;
    '-p -s LABEL -o value '* )
        if [ "$SCENARIO" = wrong_label ]; then echo OTHER; else echo TODDLERBOX; fi ;;
    *) echo "Unexpected blkid arguments: $*" >&2; exit 1 ;;
esac
''',
        "mount": r'''
echo "mount $*" >> "$CALL_LOG"
case "$*" in
    *'/dev/sdb3 '*) exit 1 ;;
esac
if [ "$SCENARIO" = mount_failure ]; then exit 1; fi
exit 0
''',
        "sha256sum": 'echo checksum >> "$CALL_LOG"; exit 1',
        "sh": 'echo recovery >> "$CALL_LOG"; exit 0',
    }
    for name, body in mocks.items():
        executable = tools / name
        executable.write_text("#!/bin/sh\n" + body + "\n")
        executable.chmod(0o755)
    source = installer.read_text()
    source = source.replace("/proc/cmdline", str(cmdline))
    source = source.replace("exec </dev/console >/dev/console 2>&1", f"exec </dev/null >{shlex.quote(str(console))} 2>&1")
    source = source.replace("/media/toddlerbox", str(media_dir))
    script = tmp_path / "install"
    script.write_text(source)
    env = dict(os.environ, PATH=f"{tools}:/usr/bin:/bin", SCENARIO=scenario, CALL_LOG=str(log))
    subprocess.run(["/bin/sh", str(script)], env=env, timeout=5, check=False)
    return log.read_text().splitlines() if log.exists() else [], console.read_text()


@pytest.mark.parametrize("scenario, device", [("hybrid_usb", "/dev/sdb"), ("optical", "/dev/sr0")])
def test_installer_mounts_iso_filesystem_and_reaches_checksum_gate(tmp_path, scenario, device):
    calls, console = simulate_media(tmp_path, scenario)
    assert "checksum" in calls
    assert any(call.startswith("mount ") and f" {device} " in call for call in calls)
    assert "Installer checksum failed." in console
    assert "Target whole disk" not in console


@pytest.mark.parametrize("scenario", ["wrong_label", "missing", "mount_failure"])
def test_unavailable_media_enters_recovery_without_checksum_or_disk_prompt(tmp_path, scenario):
    calls, console = simulate_media(tmp_path, scenario)
    assert "recovery" in calls
    assert "checksum" not in calls
    assert "Installer ISO9660 media not found or could not be mounted." in console
    assert "Target whole disk" not in console
    if scenario in {"wrong_label", "missing"}:
        assert not any(call.startswith("mount ") for call in calls)
