"""Release-switch failure boundaries; disk/power-loss behavior still needs a guest."""
import hashlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest


@pytest.fixture
def release_installer(monkeypatch):
    system = Path(__file__).parents[1] / "system"
    spec = importlib.util.spec_from_file_location("controller", system / "controller.py")
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    monkeypatch.setitem(sys.modules, "controller", controller)
    loader = importlib.machinery.SourceFileLoader("release_installer", str(system / "bin/toddlerbox-install-release"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    installer = importlib.util.module_from_spec(spec)
    # Importing the executable must not attempt an installation.
    spec.loader.exec_module(installer)
    monkeypatch.setattr(installer.os, "sync", lambda: None)
    return installer, controller


@pytest.fixture
def release_tree(tmp_path):
    root = tmp_path / "app"
    (root / "releases" / "old").mkdir(parents=True)
    (root / "current").symlink_to(root / "releases/old")
    mode = tmp_path / "mode"
    mode.write_text("parent\n")
    return root, mode


def bundle(tmp_path, *, schema=None, omit_schema=False, extra=None):
    release_id = "0123456789abcdef"
    files = {
        "src/toddlerbox/launcher.py": b"# launcher\n",
        ".venv/bin/python": b"python placeholder",
        "uv.lock": b"# lock\n",
    }
    if not omit_schema:
        files["data-schema.json"] = json.dumps(schema or {"version": 1, "typing": 1, "paint": 1}).encode()
    if extra:
        files.update(extra)
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as target:
        for name, data in files.items():
            member = tarfile.TarInfo(f"{release_id}/{name}")
            member.size = len(data)
            target.addfile(member, io.BytesIO(data))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return archive, digest, release_id


def test_install_persists_previous_before_switching_current(release_installer, release_tree, tmp_path, monkeypatch):
    installer, controller = release_installer
    root, mode = release_tree
    archive, digest, release_id = bundle(tmp_path)
    states = []

    def sync(directory):
        states.append((directory, (root / "current").resolve().name,
                       (root / "previous").resolve().name if (root / "previous").exists() else None))

    monkeypatch.setattr(controller, "sync_directory", sync)
    monkeypatch.setattr(installer, "sync_directory", sync)
    assert installer.install(archive, digest, root=root, mode_file=mode) == release_id
    assert states == [(root / "releases", "old", None),
                      (root, "old", "old"), (root, release_id, "old")]
    assert json.loads((root / "current/data-schema.json").read_text()) == controller.DATA_SCHEMA


def test_failed_previous_sync_never_switches_current(release_installer, release_tree, tmp_path, monkeypatch):
    installer, controller = release_installer
    root, mode = release_tree
    archive, digest, release_id = bundle(tmp_path)

    def fail(directory):
        raise OSError("directory fsync failed")

    monkeypatch.setattr(controller, "sync_directory", fail)
    with pytest.raises(OSError, match="fsync failed"):
        installer.install(archive, digest, root=root, mode_file=mode)
    assert (root / "current").resolve() == root / "releases/old"
    assert (root / "previous").resolve() == root / "releases/old"
    assert (root / "releases" / release_id).is_dir()


def test_failed_current_sync_keeps_fallback_and_visible_new_release(release_installer, release_tree, tmp_path, monkeypatch):
    installer, controller = release_installer
    root, mode = release_tree
    archive, digest, release_id = bundle(tmp_path)
    count = [0]

    def sync(directory):
        count[0] += 1
        if count[0] == 2:
            raise OSError("uncertain current durability")

    monkeypatch.setattr(controller, "sync_directory", sync)
    with pytest.raises(OSError, match="uncertain"):
        installer.install(archive, digest, root=root, mode_file=mode)
    assert (root / "current").resolve() == root / "releases" / release_id
    assert (root / "previous").resolve() == root / "releases/old"


@pytest.mark.parametrize("schema,omit", [
    ({"version": 1, "typing": 2, "paint": 1}, False),
    ({"version": 1, "typing": True, "paint": 1}, False),
    ({"version": 1, "typing": 1}, False),
    (None, True),
])
def test_install_refuses_unknown_or_incompatible_schema(release_installer, release_tree, tmp_path, schema, omit):
    installer, _ = release_installer
    root, mode = release_tree
    archive, digest, release_id = bundle(tmp_path, schema=schema, omit_schema=omit)
    with pytest.raises((ValueError, FileNotFoundError)):
        installer.install(archive, digest, root=root, mode_file=mode)
    assert (root / "current").resolve() == root / "releases/old"
    assert not (root / "releases" / release_id).exists()
    assert not (root / "previous").exists()


def test_install_refuses_child_mode_and_checksum_mismatch(release_installer, release_tree, tmp_path):
    installer, _ = release_installer
    root, mode = release_tree
    archive, digest, release_id = bundle(tmp_path)
    mode.write_text("child\n")
    with pytest.raises(ValueError, match="parent mode"):
        installer.install(archive, digest, root=root, mode_file=mode)
    mode.write_text("parent\n")
    with pytest.raises(ValueError, match="checksum"):
        installer.install(archive, "0" * 64, root=root, mode_file=mode)
    assert not (root / "releases" / release_id).exists()


def test_install_uses_verified_open_archive_when_path_is_replaced(release_installer, release_tree, tmp_path, monkeypatch):
    installer, _ = release_installer
    root, mode = release_tree
    archive, digest, release_id = bundle(tmp_path)
    file_digest = hashlib.file_digest

    def replace_after_hash(handle, algorithm):
        result = file_digest(handle, algorithm)
        archive.unlink()
        archive.write_bytes(b"not the verified archive")
        return result

    monkeypatch.setattr(installer.hashlib, "file_digest", replace_after_hash)
    assert installer.install(archive, digest, root=root, mode_file=mode) == release_id


def test_install_rejects_archive_path_escape(release_installer, release_tree, tmp_path):
    installer, _ = release_installer
    root, mode = release_tree
    archive, digest, release_id = bundle(tmp_path, extra={"../../escape": b"unsafe"})
    with pytest.raises(ValueError, match="Unsafe archive path"):
        installer.install(archive, digest, root=root, mode_file=mode)
    assert not (root / "releases" / release_id).exists()
    assert not (root / "releases/escape").exists()
