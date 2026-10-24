"""Small image hardening: SysRq, recordfail, first-boot retries and clock sanity."""
import datetime
from pathlib import Path

import pytest

from system.tbx_sync.state import clock_plausible
from test_appliance import modules  # noqa: F401  (fixture)

ROOT = Path(__file__).parents[1]
UTC = datetime.timezone.utc


def test_image_limits_sysrq_and_recordfail_wait():
    recipe = (ROOT / "system/configure-rootfs.sh").read_text()
    assert "kernel.sysrq = 16" in recipe and "/etc/sysctl.d/90-toddlerbox.conf" in recipe
    assert "GRUB_RECORDFAIL_TIMEOUT=5" in recipe


def test_first_boot_password_retries_are_bounded():
    script = (ROOT / "system/bin/toddlerbox-firstboot").read_text()
    assert "for attempt in 1 2 3" in script and "Restart the laptop to try again" in script


def versions(tmp_path, snapshot="20260926T000000Z"):
    path = tmp_path / "opt/toddlerbox/versions.env"
    path.parent.mkdir(parents=True)
    path.write_text(f"UBUNTU_SNAPSHOT={snapshot}\nUV_VERSION=0.12.19\n")
    return path


def test_sync_refuses_a_clock_earlier_than_the_build(tmp_path):
    path = versions(tmp_path)
    assert not clock_plausible(path, current=datetime.datetime(2001, 1, 1, tzinfo=UTC))
    assert clock_plausible(path, current=datetime.datetime(2026, 10, 23, tzinfo=UTC))
    assert clock_plausible(tmp_path / "missing.env")


def test_maintenance_network_actions_explain_a_wrong_clock(modules, tmp_path, monkeypatch):
    core, maintenance = modules[1], modules[3]
    versions(tmp_path)
    problem = core.clock_problem(tmp_path, now=datetime.datetime(2001, 1, 1, tzinfo=UTC))
    assert "2001-01-01" in problem and "2026-09-26" in problem and "Set the date and time" in problem
    assert core.clock_problem(tmp_path, now=datetime.datetime(2026, 10, 23, tzinfo=UTC)) is None
    monkeypatch.setattr(maintenance, "guard", lambda **kwargs: None)
    monkeypatch.setattr(maintenance, "clock_problem", lambda: "The laptop clock says 2001-01-01.")
    with pytest.raises(ValueError, match="laptop clock"):
        maintenance.root_action("updates", [])
