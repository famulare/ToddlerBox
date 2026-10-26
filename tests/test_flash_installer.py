"""Exercise the destructive writer's gates with simulated Linux disk commands.

No test opens a block device or invokes the real dd, blockdev, or cmp.
"""
import os
from pathlib import Path
import shlex
import subprocess

import pytest


SCRIPT = Path(__file__).parents[1] / "system/flash-installer.sh"
MOCK_DISKS = r'''
lsblk() {
    case "$2" in
        TYPE)
            if [[ $1 == -dnro ]]; then
                if [[ $SCENARIO == partition ]]; then echo part; else echo disk; fi
            elif [[ $SCENARIO == mapping ]]; then
                printf 'disk\npart\ncrypt\n'
            else
                printf 'disk\npart\n'
            fi ;;
        RO) if [[ $SCENARIO == readonly ]]; then echo 1; else echo 0; fi ;;
        MOUNTPOINTS)
            case $SCENARIO in
                mounted) echo '/media/transfer drive' ;;
                swap) echo '[SWAP]' ;;
                automount)
                    if [[ -f $CALL_LOG.mount ]]; then echo '/media/usb'; fi
                    touch "$CALL_LOG.mount" ;;
                *) printf '\n\n' ;;
            esac ;;
        *) echo '/dev/sdz 16G Test USB' ;;
    esac
}
blockdev() {
    if [[ $1 == --getsize64 ]]; then
        if [[ $SCENARIO == small ]]; then echo 1; else echo 16777216; fi
    else
        echo flush >> "$CALL_LOG"
    fi
}
readlink() { echo /dev/sdz; }
dd() {
    echo write >> "$CALL_LOG"
    [[ $SCENARIO != write_failure ]]
}
cmp() {
    echo verify >> "$CALL_LOG"
    [[ $SCENARIO != verify_failure ]]
}
'''


def run_simulation(tmp_path, scenario, operation, answer=""):
    log = tmp_path / "calls"
    env = dict(os.environ, SCENARIO=scenario, CALL_LOG=str(log))
    result = subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(SCRIPT))}\n{MOCK_DISKS}\n{operation}"],
        input=answer, text=True, capture_output=True, env=env, timeout=5,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


@pytest.mark.parametrize("scenario, message", [
    ("partition", "whole disk"),
    ("readonly", "read-only"),
    ("small", "too small"),
    ("mounted", "mounted filesystems"),
    ("swap", "active swap"),
    ("mapping", "active device mapping"),
])
def test_unsafe_target_is_rejected_before_any_write(tmp_path, scenario, message):
    result, calls = run_simulation(tmp_path, scenario, 'flash /tmp/installer.iso /dev/sdz 1024')
    assert result.returncode != 0
    assert message in result.stderr
    assert calls == []


@pytest.mark.parametrize("answer", ["\n", "yes\n", "ERASE /dev/sdy\n", ""])
def test_cancellation_and_wrong_confirmation_never_write(tmp_path, answer):
    result, calls = run_simulation(tmp_path, "safe", 'flash /tmp/installer.iso /dev/sdz 1024', answer)
    assert result.returncode == 0
    assert "Cancelled; nothing written" in result.stdout
    assert calls == []


def test_disk_that_automounts_during_confirmation_is_rejected(tmp_path):
    result, calls = run_simulation(tmp_path, "automount", 'flash /tmp/installer.iso /dev/sdz 1024', "ERASE /dev/sdz\n")
    assert result.returncode != 0
    assert "mounted filesystems" in result.stderr
    assert calls == []


def test_success_requires_write_then_flush_then_readback(tmp_path):
    result, calls = run_simulation(tmp_path, "safe", 'flash /tmp/installer.iso /dev/sdz 1024', "ERASE /dev/sdz\n")
    assert result.returncode == 0
    assert calls == ["write", "flush", "verify"]
    assert "Done. The verified installer" in result.stdout


@pytest.mark.parametrize("scenario, expected_calls", [
    ("write_failure", ["write"]),
    ("verify_failure", ["write", "flush", "verify"]),
])
def test_write_or_verification_failure_never_reports_success(tmp_path, scenario, expected_calls):
    result, calls = run_simulation(tmp_path, scenario, 'flash /tmp/installer.iso /dev/sdz 1024', "ERASE /dev/sdz\n")
    assert result.returncode != 0
    assert calls == expected_calls
    assert "Done." not in result.stdout
