"""One bad Drive item never blocks backing up the child's work; killed jobs clean up."""
import io
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1]))
from sync_fixtures import MemoryDrive, package, paths, png, typing  # noqa: E402
from system.tbx_sync import cli  # noqa: E402
from system.tbx_sync.install import restore_archives, setup  # noqa: E402
from system.tbx_sync.remote import Rclone, TransferError  # noqa: E402
from system.tbx_sync.safeio import digest  # noqa: E402
from system.tbx_sync.state import initialize, load, sweep_staging  # noqa: E402
from system.tbx_sync.worker import Run  # noqa: E402
from test_decode_errors import broken_chunk, detailed_png  # noqa: E402


def installed(tmp_path, photos=None):
    locations = paths(tmp_path / "device")
    archive, checksum = package(tmp_path, photos=photos)
    setup(locations, archive, checksum, minimum=0)
    (locations.data / "paint/latest.png").write_bytes(png("blue"))
    (locations.data / "typing/current.json").write_bytes(typing("hello"))
    return locations


def creations(drive, status):
    return sorted(name for name in drive.files if name.startswith("Creations/" + status["device_uuid"]))


def run(locations, drive, **kwargs):
    return Run(locations, factory=drive, save=lambda: "ok", minimum=0, **kwargs).execute()


class FailingGets(MemoryDrive):
    def get(self, remote, destination):
        if remote == "Photos/unreachable.png":
            raise TransferError("transfer-failed")
        super().get(remote, destination)


def test_bad_drive_photos_are_issues_while_creations_still_upload(tmp_path):
    locations = installed(tmp_path)
    drive = FailingGets()
    drive.files["Photos/damaged.png"] = broken_chunk(detailed_png())
    drive.files["Photos/unreachable.png"] = png("green")
    drive.files["Photos/fine.png"] = png("red")
    drive.extra_entries["Photos"] = [{"Path": "Twin.jpg", "Name": "Twin.jpg", "Size": 10, "IsDir": False},
                                     {"Path": "twin.JPG", "Name": "twin.JPG", "Size": 10, "IsDir": False}]
    status = run(locations, drive)
    assert status["state"] == "partial"
    named = {(item["issue"], item["name"]) for item in status["issue_files"]}
    assert ("photo-invalid-or-unpublishable", "damaged.png") in named
    assert ("transfer-failed", "unreachable.png") in named
    assert ("duplicate-cloud-names", "Twin.jpg") in named and ("duplicate-cloud-names", "twin.JPG") in named
    assert (locations.library / "fine.png").exists()
    uploaded = creations(drive, status)
    assert any(name.endswith("/paint/latest.png") for name in uploaded)
    assert any(name.endswith("/manifest.json") for name in uploaded)


def test_creations_upload_before_any_photo_download(tmp_path):
    locations = installed(tmp_path)
    drive = MemoryDrive()
    drive.files["Photos/new.png"] = png("red")
    run(locations, drive)
    first_photo = next(i for i, op in enumerate(drive.operations) if op[:2] == ("get", "Photos/new.png"))
    first_creation = next(i for i, op in enumerate(drive.operations)
                          if op[0] == "put" and op[1].startswith("Creations/"))
    assert first_creation < first_photo


class FailingPut(MemoryDrive):
    fail_name = None

    def put(self, source, remote, *, immutable=False):
        if self.fail_name and remote.endswith(self.fail_name):
            raise TransferError("transfer-failed")
        super().put(source, remote, immutable=immutable)


def test_failed_creation_withholds_manifest_and_old_manifest_refuses_a_mix(tmp_path):
    locations = installed(tmp_path)
    drive = FailingPut()
    first = run(locations, drive)
    root = "Creations/" + first["device_uuid"] + "/"
    old_manifest = drive.files[root + "manifest.json"]
    (locations.data / "paint/latest.png").write_bytes(png("purple"))
    (locations.data / "typing/current.json").write_bytes(typing("changed"))
    drive.fail_name = "typing/current.json"
    second = run(locations, drive)
    assert "creations-manifest-withheld" in second["issues"]
    assert drive.files[root + "manifest.json"] == old_manifest
    assert drive.files[root + "paint/latest.png"] == png("purple")
    source = tmp_path / "restore"
    for name, data in drive.files.items():
        if name.startswith(root):
            target = source / name[len(root):]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    with pytest.raises(ValueError, match="checksum mismatch"):
        restore_archives(locations, source, digest(source / "manifest.json"), minimum=0)


def test_quarantined_local_media_is_skipped_without_withholding_the_manifest(tmp_path):
    locations = installed(tmp_path)
    (locations.data / "paint/corrupt-123.png").write_bytes(b"damaged")
    drive = MemoryDrive()
    status = run(locations, drive)
    assert status["state"] == "success"
    assert status["counts"]["local_quarantined_skipped"] == 1
    assert any(name.endswith("/manifest.json") for name in creations(drive, status))


def test_initial_backup_resumes_across_bounded_runs_without_starving_creations(tmp_path, monkeypatch):
    from system.tbx_sync import worker

    photos = {f"p{i:02d}.png": png((i * 20, 0, 0)) for i in range(10)}
    locations = installed(tmp_path, photos=photos)
    drive = MemoryDrive()
    # Charge transfers to the phase clock without making fsync speed part of
    # this scheduling test. Actual subprocess deadline enforcement is tested below.
    clock = [1000.0]
    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def transfer_time(source, remote):
        if remote.startswith("Initial backup/"):
            clock[0] += 0.12

    drive.before_put = transfer_time
    runs = 0
    while not load(locations.state / "initial.json").get("complete"):
        runs += 1
        assert runs <= 6
        status = run(locations, drive, seconds=1.2)
        assert any(name.endswith("/paint/latest.png") for name in creations(drive, status))
    assert runs >= 2
    assert sorted(n for n in drive.files if n.startswith("Initial backup/")) == sorted(
        [f"Initial backup/2026-10-03/{name}" for name in photos] + ["Initial backup/2026-10-03/manifest.json"])


def test_sigterm_records_interruption_and_leaves_no_staged_child_work(tmp_path):
    locations = installed(tmp_path)
    script = textwrap.dedent(f"""
        import signal, sys, time
        sys.path.insert(0, {str(Path(__file__).parents[1])!r}); sys.path.insert(0, {str(Path(__file__).parent)!r})
        from sync_fixtures import MemoryDrive
        from system.tbx_sync.state import Paths
        from system.tbx_sync import worker
        signal.signal(signal.SIGTERM, worker._terminate)
        drive = MemoryDrive(); drive.before_put = lambda s, r: time.sleep(30)
        from pathlib import Path
        locations = Paths(Path({str(locations.config)!r}), Path({str(locations.state)!r}), Path({str(locations.data)!r}))
        print("started", flush=True)
        try:
            worker.Run(locations, factory=drive, save=lambda: "ok", minimum=0).execute()
        except worker.Terminated:
            sys.exit(143)
    """)
    child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "started"
    time.sleep(1.0)
    child.send_signal(signal.SIGTERM)
    assert child.wait(timeout=20) == 143
    assert load(locations.state / "status.json")["state"] == "interrupted"
    assert not list((locations.state / "staging").iterdir())


def test_leftover_staging_from_a_killed_job_is_swept_under_the_lock(tmp_path):
    locations = paths(tmp_path / "device")
    initialize(locations)
    for leftover in ["run-old/creations/paint", "usb-old", "import-old"]:
        (locations.state / "staging" / leftover).mkdir(parents=True)
    (locations.state / "staging/run-old/creations/paint/latest.png").write_bytes(png())
    sweep_staging(locations)
    assert not list((locations.state / "staging").iterdir())


def test_wrong_clock_certificate_failure_is_reported_as_such(tmp_path):
    locations = paths(tmp_path / "device")
    initialize(locations)
    fake = tmp_path / "rclone"
    fake.write_text("#!/bin/sh\necho 'x509: certificate has expired or is not yet valid' >&2\nexit 1\n")
    fake.chmod(0o700)
    remote = Rclone(locations, "synthetic_root_1234567890", locations.state / "staging",
                    deadline=time.monotonic() + 10, binary=str(fake), minimum=0)
    with pytest.raises(TransferError, match="clock-or-certificate"):
        remote.list("Photos")


def test_cli_shows_the_fixed_refusal_sentence(tmp_path, monkeypatch, capsys):
    locations = paths(tmp_path / "device")
    archive, _checksum = package(tmp_path)
    monkeypatch.setattr(cli, "Paths", lambda: locations)
    monkeypatch.setattr(cli, "os", SimpleNamespace(geteuid=lambda: 0, environ=os.environ))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("sys.argv", ["toddlerbox-sync", "setup", str(archive), "--sha256", "0" * 64])
    with pytest.raises(SystemExit):
        cli.main()
    assert "Archive SHA-256 mismatch" in capsys.readouterr().err


def test_wrong_clock_stops_the_job_before_any_transfer(tmp_path, monkeypatch):
    locations = installed(tmp_path)
    monkeypatch.setattr("system.tbx_sync.worker.clock_plausible", lambda: False)
    drive = MemoryDrive()
    status = run(locations, drive)
    assert status["state"] == "partial" and "clock-or-certificate" in status["issues"]
    assert not drive.operations


def test_missing_initial_original_still_lets_creations_upload(tmp_path):
    locations = installed(tmp_path)
    initial = load(locations.state / "initial.json")
    original = next(iter(initial["files"]))
    (locations.state / "initial" / initial["package_id"] / original).unlink()
    drive = MemoryDrive()
    status = run(locations, drive)
    assert "initial-backup-local-failure" in status["issues"]
    assert any(name.endswith("/paint/latest.png") for name in creations(drive, status))


def test_quarantined_media_is_listed_as_excluded_in_the_manifest(tmp_path):
    locations = installed(tmp_path)
    (locations.data / "paint/corrupt-123.png").write_bytes(b"damaged")
    drive = MemoryDrive()
    status = run(locations, drive)
    manifest = json.loads(drive.files["Creations/" + status["device_uuid"] + "/manifest.json"])
    assert manifest["excluded"] == ["paint/corrupt-123.png"]
    assert "paint/corrupt-123.png" not in manifest["files"]
