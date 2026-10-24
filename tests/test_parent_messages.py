"""Parents see why an operation was refused, and a refused rollback wedges nothing."""
import json
import urllib.error

import pytest

from test_appliance import appliance_machine, modules  # noqa: F401  (fixtures)
from test_update_bundle import machine, make_bundle, updater  # noqa: F401  (fixtures)


def test_refused_rollback_leaves_no_maintenance_marker(appliance_machine, updater, modules, tmp_path):
    module, _ = updater
    recovery = modules[0]
    bundle, digest = make_bundle(tmp_path, module)
    module.run(bundle, digest, root=appliance_machine)
    job, _value = module.latest(appliance_machine / module.STATE)
    (job / "toddlerbox-session").write_bytes(b"damaged backup")
    with pytest.raises(ValueError):
        module.run(rollback=True, root=appliance_machine)
    assert not (appliance_machine / recovery.STATE / "maintenance").exists()


def run_main(maintenance, monkeypatch, error):
    def refuse(*_args):
        raise error
    monkeypatch.setattr(maintenance, "root_action", refuse)
    monkeypatch.setattr("sys.argv", ["toddlerbox-maintenance", "--action", "accept"])
    with pytest.raises(SystemExit) as stopped:
        maintenance.main()
    return str(stopped.value)


def test_fixed_refusal_sentence_is_shown_to_the_parent(modules, monkeypatch):
    message = run_main(modules[3], monkeypatch, ValueError(
        "Test the candidate child session for at least ten seconds, then return to parent mode"))
    assert "Test the candidate child session" in message


def test_offline_refusal_suggests_wifi_and_clock(modules, monkeypatch):
    message = run_main(modules[3], monkeypatch, urllib.error.URLError("certificate is not yet valid"))
    assert "Wi-Fi" in message and "date and time" in message


def test_status_reports_archive_counts_without_names(appliance_machine, modules, monkeypatch):
    maintenance = modules[3]
    data = appliance_machine / "var/lib/toddlerbox"
    (data / "paint").mkdir(parents=True, exist_ok=True)
    (data / "typing/archive").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(maintenance.subprocess, "run",
                        lambda *a, **k: maintenance.subprocess.CompletedProcess(a, 0, stdout="active\n"))
    before = maintenance.report(appliance_machine)["archives"]
    for name in ["latest.png", "2026-10-23_120000.png", "recovered-1.png", "corrupt-2.png", ".x.tmp.png"]:
        (data / "paint" / name).write_bytes(b"x")
    for name in ["1.json", "2.json", "corrupt-3.json"]:
        (data / "typing/archive" / name).write_bytes(b"{}")
    report = maintenance.report(appliance_machine)
    assert report["archives"]["paint"] == before["paint"] + 2
    assert report["archives"]["typing"] == before["typing"] + 2
    text = json.dumps(report)
    assert "2026-10-23_120000" not in text and "recovered-1" not in text
