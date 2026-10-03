"""Exercise real updater files/journal with only OS commands replaced by a spy."""
import hashlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

import pytest


@pytest.fixture
def updater(monkeypatch):
    path = Path(__file__).parents[1] / "system/update_bundle.py"
    spec = importlib.util.spec_from_file_location("update_bundle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, "update_bundle", module)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")
    calls = []
    monkeypatch.setattr(module, "command", lambda args: calls.append(args))
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="libraries available"))
    return module, calls


@pytest.fixture
def machine(tmp_path, updater):
    module, _ = updater
    root = tmp_path / "machine"
    (root / "run/toddlerbox-system").mkdir(parents=True)
    (root / "run/toddlerbox-system/mode").write_text("parent\n")
    (root / "etc").mkdir()
    (root / "etc/os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
    for relative, _ in module.FILES.values():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
    for name in ("controller.py", "toddlerbox-session"):
        (root / module.FILES[name][0]).write_bytes(b"old-" + name.encode())
    (root / module.APP / "releases/old").mkdir(parents=True)
    (root / module.APP / "current").symlink_to("releases/old")
    for relative in ("var/lib/toddlerbox/paint/current.png", "etc/toddlerbox/config.yaml",
                     "etc/toddlerbox-sync/rclone.conf", "var/lib/toddlerbox-sync/device.json"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"keep-private-and-child-work")
    return root


def make_bundle(tmp_path, module, *, extra=None, files=None, app=False):
    content = {"controller.py": b"new-controller", "toddlerbox-session": b"new-session",
               "toddlerbox-cage": b"synthetic-cage", "toddlerbox-volume": b"new-volume"}
    if files is not None:
        content = files
    manifest = {"format": 1, "source": {"git": "synthetic"},
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in content.items()},
                "app": hashlib.sha256(b"synthetic-app").hexdigest() if app else None}
    path = tmp_path / "update.pyz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("__main__.py", "")
        archive.writestr("update_bundle.py", "")
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in content.items():
            archive.writestr("payload/" + name, data)
        if app:
            archive.writestr("app.tar.gz", b"synthetic-app")
        if extra:
            archive.writestr(*extra)
    return path, module.sha(path)


def protected(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for name in ("var/lib/toddlerbox", "etc/toddlerbox", "etc/toddlerbox-sync", "var/lib/toddlerbox-sync")
            for path in (root / name).rglob("*") if path.is_file()}


def test_success_repeat_and_rollback_preserve_work_and_credentials(updater, machine, tmp_path):
    module, calls = updater
    before = protected(machine)
    archive, digest = make_bundle(tmp_path, module)
    assert "Update installed" in module.run(archive, digest, root=machine)
    assert (machine / module.FILES["controller.py"][0]).read_bytes() == b"new-controller"
    assert calls[-1] == ["systemctl", "start", "--no-block", module.SERVICE]
    assert "already installed" in module.run(archive, digest, root=machine)
    assert "restored" in module.run(rollback=True, root=machine)
    assert (machine / module.FILES["controller.py"][0]).read_bytes() == b"old-controller.py"
    assert not (machine / module.FILES["toddlerbox-volume"][0]).exists()
    assert protected(machine) == before
    with pytest.raises(ValueError, match="No pending"):
        module.run(rollback=True, root=machine)


@pytest.mark.parametrize("problem", ["child", "checksum", "traversal", "unknown_destination", "symlink", "disk_full", "payload_hash"])
def test_refuse_before_os_commands(updater, machine, tmp_path, monkeypatch, problem):
    module, calls = updater
    files = {"../../etc/shadow": b"unsafe"} if problem == "unknown_destination" else None
    archive, digest = make_bundle(tmp_path, module, files=files,
                                  extra=("../outside", b"unsafe") if problem == "traversal" else None)
    if problem == "child":
        (machine / "run/toddlerbox-system/mode").write_text("child")
    elif problem == "checksum":
        digest = "0" * 64
    elif problem == "symlink":
        target = machine / module.FILES["controller.py"][0]
        target.unlink()
        target.symlink_to(machine / "etc/toddlerbox-sync/rclone.conf")
    elif problem == "disk_full":
        monkeypatch.setattr(module.shutil, "disk_usage", lambda p: type("Usage", (), {"free": 0})())
    elif problem == "payload_hash":
        with zipfile.ZipFile(archive) as inp:
            items = {name: inp.read(name) for name in inp.namelist()}
        items["payload/controller.py"] = b"changed"
        with zipfile.ZipFile(archive, "w") as out:
            for name, data in items.items():
                out.writestr(name, data)
        digest = module.sha(archive)
    with pytest.raises((ValueError, OSError)):
        module.run(archive, digest, root=machine)
    assert calls == []


def test_offline_apt_failure_never_replaces_files(updater, machine, tmp_path, monkeypatch):
    module, calls = updater
    archive, digest = make_bundle(tmp_path, module)
    def offline(args):
        raise subprocess.CalledProcessError(100, args)
    monkeypatch.setattr(module, "command", offline)
    with pytest.raises(subprocess.CalledProcessError):
        module.run(archive, digest, root=machine)
    assert (machine / module.FILES["controller.py"][0]).read_bytes() == b"old-controller.py"
    assert module.latest(machine / module.STATE) is None


def test_failed_replacement_rolls_back_all_files(updater, machine, tmp_path, monkeypatch):
    module, calls = updater
    archive, digest = make_bundle(tmp_path, module)
    actual = module.replace
    failed = False
    def fail_once(source, target, mode):
        nonlocal failed
        if target == machine / module.FILES["toddlerbox-session"][0] and not failed:
            failed = True
            raise OSError("synthetic interrupted write")
        return actual(source, target, mode)
    monkeypatch.setattr(module, "replace", fail_once)
    with pytest.raises(OSError, match="interrupted write"):
        module.run(archive, digest, root=machine)
    assert (machine / module.FILES["controller.py"][0]).read_bytes() == b"old-controller.py"
    assert module.latest(machine / module.STATE)[1]["status"] == "rolled-back"
    assert calls[-1] == ["systemctl", "start", "--no-block", module.SERVICE]


def test_interrupted_update_requires_explicit_rollback(updater, machine, tmp_path):
    module, _ = updater
    archive, digest = make_bundle(tmp_path, module)
    module.run(archive, digest, root=machine)
    job, state = module.latest(machine / module.STATE)
    state["status"] = "applying"
    module.record(job / "state.json", state)
    with pytest.raises(ValueError, match="Interrupted update"):
        module.run(archive, digest, root=machine)
    module.run(rollback=True, root=machine)
    assert (machine / module.FILES["controller.py"][0]).read_bytes() == b"old-controller.py"


def test_bad_backup_is_refused_before_any_file_restore(updater, machine, tmp_path):
    module, _ = updater
    archive, digest = make_bundle(tmp_path, module)
    module.run(archive, digest, root=machine)
    job, _ = module.latest(machine / module.STATE)
    (job / "toddlerbox-session").write_bytes(b"corrupt backup")
    with pytest.raises(ValueError, match="backup checksum"):
        module.run(rollback=True, root=machine)
    assert (machine / module.FILES["controller.py"][0]).read_bytes() == b"new-controller"


def test_app_install_failure_restores_release_links_and_system(updater, machine, tmp_path, monkeypatch):
    module, calls = updater
    archive, digest = make_bundle(tmp_path, module, app=True)
    def command(args):
        calls.append(args)
        if "toddlerbox-install-release" in args[0]:
            base = machine / module.APP
            (base / "releases/new").mkdir()
            (base / "current").unlink()
            (base / "current").symlink_to("releases/new")
            raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(module, "command", command)
    with pytest.raises(subprocess.CalledProcessError):
        module.run(archive, digest, root=machine)
    assert (machine / module.APP / "current").resolve().name == "old"
    assert not (machine / module.APP / "previous").exists()
    assert (machine / module.FILES["controller.py"][0]).read_bytes() == b"old-controller.py"


def test_verified_open_descriptor_survives_path_substitution(updater, tmp_path, monkeypatch):
    module, _ = updater
    archive, digest = make_bundle(tmp_path, module)
    actual = module.hashlib.file_digest
    def swap(handle, algorithm):
        result = actual(handle, algorithm)
        if Path(handle.name) == archive:
            archive.unlink()
            archive.write_bytes(b"not a zip")
        return result
    monkeypatch.setattr(module.hashlib, "file_digest", swap)
    stage = tmp_path / "stage"
    stage.mkdir()
    module.stage_bundle(archive, digest, stage)
    assert (stage / "controller.py").read_bytes() == b"new-controller"


def test_combined_update_uses_real_app_installer_and_rolls_back_links(updater, machine, tmp_path, monkeypatch):
    module, calls = updater
    system = Path(__file__).parents[1] / "system"
    spec = importlib.util.spec_from_file_location("controller", system / "controller.py")
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    monkeypatch.setitem(sys.modules, "controller", controller)
    loader = importlib.machinery.SourceFileLoader("actual_release_installer", str(system / "bin/toddlerbox-install-release"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    monkeypatch.setattr(installer.os, "sync", lambda: None)
    app = io.BytesIO()
    with tarfile.open(fileobj=app, mode="w:gz") as archive:
        for name, data in {"src/toddlerbox/launcher.py": b"# synthetic launcher",
                           ".venv/bin/python": b"synthetic interpreter", "uv.lock": b"lock",
                           "data-schema.json": json.dumps(controller.DATA_SCHEMA).encode()}.items():
            item = tarfile.TarInfo("0123456789abcdef/" + name)
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
    archive, _ = make_bundle(tmp_path, module, app=True)
    with zipfile.ZipFile(archive) as inp:
        entries = {name: inp.read(name) for name in inp.namelist()}
    entries["app.tar.gz"] = app.getvalue()
    manifest = json.loads(entries["manifest.json"])
    manifest["app"] = hashlib.sha256(app.getvalue()).hexdigest()
    entries["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(archive, "w") as out:
        for name, data in entries.items():
            out.writestr(name, data)
    def real_app(args):
        calls.append(args)
        if "toddlerbox-install-release" in args[0]:
            installer.install(Path(args[1]), args[2], root=machine / module.APP,
                              mode_file=machine / "run/toddlerbox-system/mode")
    monkeypatch.setattr(module, "command", real_app)
    before = protected(machine)
    module.run(archive, module.sha(archive), root=machine)
    assert (machine / module.APP / "current").resolve().name == "0123456789abcdef"
    assert (machine / module.APP / "previous").resolve().name == "old"
    module.run(rollback=True, root=machine)
    assert (machine / module.APP / "current").resolve().name == "old"
    assert not (machine / module.APP / "previous").exists()
    assert (machine / module.APP / "releases/0123456789abcdef").is_dir()
    assert protected(machine) == before
