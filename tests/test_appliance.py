"""Real recovery bytes/journals, signed metadata and restricted parent state."""
import importlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from test_update_bundle import updater, machine, make_bundle, protected


@pytest.fixture
def modules(monkeypatch):
    system = Path(__file__).parents[1] / "system"
    monkeypatch.syspath_prepend(str(system))
    recovery = importlib.import_module("boot_recovery")
    core = importlib.import_module("appliance")
    releases = importlib.import_module("release_client")
    path = system / "bin/toddlerbox-maintenance"
    loader = importlib.machinery.SourceFileLoader("maintenance_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    maintenance = importlib.util.module_from_spec(spec)
    loader.exec_module(maintenance)
    return recovery, core, releases, maintenance


@pytest.fixture
def appliance_machine(machine, updater, modules, monkeypatch):
    module, _ = updater
    state = machine / "var/lib/toddlerbox-system"
    state.mkdir(exist_ok=True)
    (state / "appliance-v1").touch()
    (state / "updates").mkdir()
    (state / "release-sequence.json").write_text('{"sequence":1}')
    for relative, mode in module.FILES.values():
        path = machine / relative
        if path.exists():
            path.chmod(mode)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="installed\n" * len(module.PACKAGES)))
    return machine


def pending(root, updater, tmp_path):
    module, _ = updater
    bundle, digest = make_bundle(tmp_path, module)
    module.run(bundle, digest, root=root)
    return bundle, digest


def test_candidate_requires_observation_and_parent_acceptance(appliance_machine, updater, modules, tmp_path):
    recovery, core, _, _ = modules
    before = protected(appliance_machine)
    pending(appliance_machine, updater, tmp_path)
    job, value = recovery.latest(appliance_machine)
    assert value["status"] == "pending"
    with pytest.raises(ValueError, match="Test the candidate"):
        core.accept(appliance_machine)
    core._candidate_entry(appliance_machine)
    core.observed(appliance_machine)
    core.accept(appliance_machine)
    assert recovery.latest(appliance_machine)[1]["status"] == "accepted"
    assert protected(appliance_machine) == before
    assert recovery.gate(appliance_machine)


def test_second_pending_install_is_refused(appliance_machine, updater, modules, tmp_path):
    bundle, digest = pending(appliance_machine, updater, tmp_path)
    with pytest.raises(ValueError, match="Interrupted update"):
        updater[0].run(bundle, digest, root=appliance_machine)


@pytest.mark.parametrize("event", ["applying", "restoring", "failed-controller", "exhausted"])
def test_boot_restores_known_pair_and_work_survives(appliance_machine, updater, modules, tmp_path, event):
    recovery, core, _, _ = modules
    before = protected(appliance_machine)
    pending(appliance_machine, updater, tmp_path)
    job, value = recovery.latest(appliance_machine)
    if event in {"applying", "restoring"}:
        value["status"] = event
    elif event == "exhausted":
        value["attempts"] = 2
    recovery.record(job / "state.json", value)
    assert recovery.gate(appliance_machine, failure=event == "failed-controller")
    assert recovery.latest(appliance_machine)[1]["status"] == "rolled-back"
    assert (appliance_machine / updater[0].FILES["controller.py"][0]).read_bytes() == b"old-controller.py"
    assert (appliance_machine / recovery.STATE / "parent-mode").exists()
    assert protected(appliance_machine) == before


@pytest.mark.parametrize("problem", ["backup", "missing-backup", "state", "symlink", "hardlink"])
def test_bad_backup_never_promoted_or_restored(appliance_machine, updater, modules, tmp_path, problem):
    recovery, core, _, _ = modules
    pending(appliance_machine, updater, tmp_path)
    job, value = recovery.latest(appliance_machine)
    path = job / "controller.py"
    if problem == "backup":
        path.write_bytes(b"corrupt")
    elif problem == "missing-backup":
        path.unlink()
    elif problem == "state":
        value["attempts"] = "two"
        recovery.record(job / "state.json", value)
    elif problem == "symlink":
        path.unlink()
        path.symlink_to(appliance_machine / "etc/toddlerbox-sync/rclone.conf")
    elif problem == "hardlink":
        (job / "extra-link").hardlink_to(path)
    controller_before = (appliance_machine / updater[0].FILES["controller.py"][0]).read_bytes()
    assert not recovery.gate(appliance_machine)
    assert (appliance_machine / recovery.STATE / "recovery-error").exists()
    assert (appliance_machine / updater[0].FILES["controller.py"][0]).read_bytes() == controller_before
    with pytest.raises((OSError, ValueError)):
        core._candidate_entry(appliance_machine)


@pytest.mark.parametrize("content", [[], None, 7, "invalid"])
@pytest.mark.parametrize("target", ["journal", "marker"])
def test_non_object_recovery_state_latches_parent(appliance_machine, updater, modules, tmp_path, content, target):
    recovery = modules[0]
    pending(appliance_machine, updater, tmp_path)
    job, _ = recovery.latest(appliance_machine)
    path = job / "state.json" if target == "journal" else appliance_machine / recovery.STATE / "updates/latest.json"
    recovery.record(path, content)
    assert recovery.gate(appliance_machine) is False
    assert (appliance_machine / recovery.STATE / "recovery-error").read_bytes() == b"ValueError\n"
    assert (appliance_machine / recovery.STATE / "parent-mode").exists()


def test_restore_interruption_resumes_using_resident_code(appliance_machine, updater, modules, tmp_path, monkeypatch):
    recovery = modules[0]
    pending(appliance_machine, updater, tmp_path)
    job, value = recovery.latest(appliance_machine)
    real = recovery.atomic
    fired = False
    def interrupted(path, data, mode=0o600):
        nonlocal fired
        real(path, data, mode)
        if path == appliance_machine / updater[0].FILES["controller.py"][0] and not fired:
            fired = True
            raise OSError("Synthetic power interruption")
    monkeypatch.setattr(recovery, "atomic", interrupted)
    assert not recovery.gate(appliance_machine, failure=True)
    assert recovery.latest(appliance_machine)[1]["status"] == "restoring"
    monkeypatch.setattr(recovery, "atomic", real)
    assert recovery.gate(appliance_machine)
    assert recovery.latest(appliance_machine)[1]["status"] == "rolled-back"
    assert not (appliance_machine / recovery.STATE / "recovery-error").exists()


def test_setup_requires_actual_recovery_test_and_preserves_checks(appliance_machine, modules):
    recovery, core, _, _ = modules
    for step in core.STEPS:
        core.check(step, "skipped", appliance_machine)
    with pytest.raises(ValueError, match="confirm authenticated"):
        core.finish(appliance_machine)
    with pytest.raises(ValueError, match="supervised child test"):
        core.check("recovery", "passed", appliance_machine)
    (appliance_machine / "run/toddlerbox-system/setup-recovery-observed").touch()
    core.check("recovery", "passed", appliance_machine)
    core.finish(appliance_machine)
    assert core.progress(appliance_machine)["checks"]["drive"] == "skipped"
    assert (appliance_machine / recovery.STATE / "setup-complete").exists()
    (appliance_machine / "run/toddlerbox-system/mode").write_text("child")
    with pytest.raises(ValueError, match="parent mode"):
        core.check("network", "passed", appliance_machine)


@pytest.fixture
def signing():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    key = Ed25519PrivateKey.generate()
    value = {"format": 1, "channel": "stable", "sequence": 10, "tag": "test-1", "source": "0" * 16,
             "platform": "ubuntu24.04-x86_64", "schema": {"version": 1, "typing": 1, "paint": 1},
             "asset": "ToddlerBox-update.pyz", "bytes": 100, "sha256": "0" * 64}
    public = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return key, public, value


@pytest.mark.parametrize("problem", [None, "signature", "platform", "schema", "path", "size", "channel", "fields"])
def test_signed_release_contract(modules, signing, problem):
    key, public, value = signing
    if problem == "platform": value["platform"] = "arm"
    if problem == "schema": value["schema"]["typing"] = 2
    if problem == "path": value["tag"] = "../../private"
    if problem == "size": value["bytes"] = True
    if problem == "channel": value["channel"] = "testing"
    if problem == "fields": value["command"] = "arbitrary"
    data = json.dumps(value).encode()
    signature = key.sign(data)
    if problem == "signature": signature = b"x" * 64
    if problem:
        with pytest.raises(ValueError): modules[2].verify(data, signature, public)
    else:
        assert modules[2].verify(data, signature, public) == value


def test_key_rotation_overlap_verifies_with_either_trusted_key(modules, signing):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    old, public, value = signing
    new = Ed25519PrivateKey.generate()
    new_public = new.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    data = json.dumps(value).encode()
    signatures = old.sign(data) + new.sign(data)
    for ring in (public, new_public, public + new_public):
        assert modules[2].verify(data, signatures, ring) == value


def test_catalog_rejects_signed_downgrade(appliance_machine, modules, signing, monkeypatch):
    recovery, _, releases, _ = modules
    key, public, value = signing
    (appliance_machine / releases.PUBLIC_KEY).write_bytes(public)
    data = json.dumps(value).encode()
    def download(url, target, maximum, **kwargs):
        target.write_bytes(key.sign(data) if url.endswith(".sig") else data)
    monkeypatch.setattr(releases, "download", download)
    assert releases.catalog(appliance_machine)["sequence"] == 10
    value["sequence"] = 9
    data = json.dumps(value).encode()
    with pytest.raises(ValueError, match="Older signed"):
        releases.catalog(appliance_machine)


@pytest.mark.parametrize("url", ["http://github.com/x", "https://github.com.evil/x", "https://user@github.com/x", "https://github.com:8443/x", "file:///etc/passwd"])
def test_release_download_rejects_other_destinations(modules, url):
    with pytest.raises(ValueError): modules[2].check_url(url)


def test_report_excludes_synthetic_private_content(appliance_machine, modules, monkeypatch):
    maintenance = modules[3]
    monkeypatch.setattr(maintenance.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="secret-network-name"))
    result = json.dumps(maintenance.report(appliance_machine))
    for forbidden in ("secret-network-name", "keep-private-and-child-work", "rclone.conf", "current.png", "device_uuid"):
        assert forbidden not in result
    assert '"NetworkManager": "unknown"' in result


def test_setup_routes_to_parent_without_completion(tmp_path, monkeypatch):
    from test_system_controller import controller
    state, runtime = tmp_path / "state", tmp_path / "run"
    state.mkdir(); runtime.mkdir()
    (state / "appliance-v1").touch()
    monkeypatch.setattr(controller, "STATE", state)
    monkeypatch.setattr(controller, "RUNTIME", runtime)
    assert controller.startup_mode() == ("parent", False)
    (runtime / "controller-started").unlink()
    (state / "setup-complete").touch()
    assert controller.startup_mode() == ("child", False)


def test_observation_cannot_span_freeze_or_session_restart():
    from test_system_controller import controller
    window = controller.ObservationWindow()
    assert not window.frame(0)
    assert not window.frame(100)
    assert all(not window.frame(t) for t in range(101, 110))
    assert window.frame(110)
    assert not window.frame(111)
    window.reset()
    assert not window.frame(112)
    assert all(not window.frame(t) for t in range(113, 122))
    assert window.frame(122)


def test_observation_is_bound_to_one_pinned_launcher_generation():
    from test_system_controller import controller
    window = controller.ObservationWindow()
    assert all(not window.frame(t, generation=1) for t in range(10))
    assert not window.frame(10, generation=2)
    assert all(not window.frame(t, generation=2) for t in range(11, 20))
    assert window.frame(20, generation=2)
    assert not window.frame(21, generation=3)


def test_intentional_restart_does_not_restore_and_failed_repair_never_loops(appliance_machine, updater, modules, tmp_path):
    recovery, core, _, _ = modules
    pending(appliance_machine, updater, tmp_path)
    assert (appliance_machine / "run/toddlerbox-system/maintenance-restart").exists()
    assert not core.needs_candidate_recovery(True, True, appliance_machine)
    assert core.needs_candidate_recovery(True, False, appliance_machine)
    (appliance_machine / recovery.STATE / "recovery-error").touch()
    assert not core.needs_candidate_recovery(True, False, appliance_machine)


def test_failed_session_invalidates_acceptance(appliance_machine, updater, modules, tmp_path):
    recovery, core, _, _ = modules
    pending(appliance_machine, updater, tmp_path)
    core._candidate_entry(appliance_machine)
    core.observed(appliance_machine)
    core.invalidate_observation(appliance_machine)
    with pytest.raises(ValueError, match="Test the candidate"):
        core.accept(appliance_machine)


def test_shared_lock_blocks_candidate_and_second_install(appliance_machine, updater, modules, tmp_path):
    _, core, _, _ = modules
    bundle, digest = make_bundle(tmp_path, updater[0])
    with core.maintenance_lock(appliance_machine):
        with pytest.raises(BlockingIOError):
            updater[0].run(bundle, digest, root=appliance_machine)
    assert not updater[1]


def test_updater_rechecks_parent_after_acquiring_lock(appliance_machine, updater, tmp_path, monkeypatch):
    from contextlib import contextmanager
    @contextmanager
    def raced(state):
        (appliance_machine / "run/toddlerbox-system/mode").write_text("child")
        yield
    monkeypatch.setattr(updater[0], "lock", raced)
    bundle, digest = make_bundle(tmp_path, updater[0])
    with pytest.raises(ValueError, match="parent mode"):
        updater[0].run(bundle, digest, root=appliance_machine)
    assert not updater[1]


def test_readonly_status_survives_failed_maintenance(appliance_machine, modules):
    recovery, core, _, _ = modules
    (appliance_machine / recovery.STATE / "maintenance").touch()
    (appliance_machine / "run/toddlerbox-system/mode").unlink()
    core.guard(appliance_machine, readonly=True)
    with pytest.raises(OSError): core.guard(appliance_machine)


def test_interrupted_apt_blocks_bundle_but_allows_repair(appliance_machine, updater, modules, tmp_path):
    recovery, core, _, _ = modules
    (appliance_machine / recovery.STATE / "apt-maintenance").touch()
    bundle, digest = make_bundle(tmp_path, updater[0])
    with pytest.raises(ValueError, match="Ubuntu repair"):
        updater[0].run(bundle, digest, root=appliance_machine)
    core.guard(appliance_machine, allow_apt=True)
    assert not updater[1]


def test_sequence_change_during_download_refused_inside_install_lock(appliance_machine, updater, modules, tmp_path):
    releases = modules[2]
    bundle, digest = make_bundle(tmp_path, updater[0])
    (appliance_machine / "var/lib/toddlerbox-system/release-sequence.json").write_text('{"sequence":11}')
    with pytest.raises(ValueError, match="Older signed"):
        updater[0].run(bundle, digest, root=appliance_machine, release_sequence=10)
    assert not updater[1]


@pytest.mark.parametrize("dirty", [False, True])
def test_offline_ubuntu_check_blocks_child_only_if_packages_inconsistent(appliance_machine, modules, monkeypatch, dirty):
    recovery, _, _, maintenance = modules
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "apt-get" and args[-1] == "update":
            raise subprocess.CalledProcessError(100, args)
        return subprocess.CompletedProcess(args, 0, stdout="unconfigured packages" if args == ["dpkg", "--audit"] and dirty else "")
    monkeypatch.setattr(maintenance.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        maintenance.ubuntu_updates(appliance_machine)
    assert (appliance_machine / recovery.STATE / "apt-maintenance").exists() is dirty
    assert not (appliance_machine / recovery.STATE / "ubuntu-maintenance.json").exists()
    first_args, first_options = calls[0]
    assert "--force-confold" in first_args
    assert first_options["stdin"] == subprocess.DEVNULL
    assert first_options["env"]["DEBIAN_FRONTEND"] == "noninteractive"
    assert "capture_output" not in first_options
