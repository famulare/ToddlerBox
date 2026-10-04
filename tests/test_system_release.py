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


def test_verified_current_release_reuse_preserves_previous(release_installer, release_tree, tmp_path):
    installer, _ = release_installer
    root, mode = release_tree
    archive, digest, release_id = bundle(tmp_path)
    installer.install(archive, digest, root=root, mode_file=mode)
    assert installer.install(archive, digest, root=root, mode_file=mode) == release_id
    assert (root / "previous").resolve() == root / "releases/old"


def test_verified_rolled_back_release_can_be_retried(release_installer, release_tree, tmp_path):
    installer, controller = release_installer
    root, mode = release_tree
    archive, digest, release_id = bundle(tmp_path)
    installer.install(archive, digest, root=root, mode_file=mode)
    controller.replace_release_link(root, "current", root / "releases/old")
    assert installer.install(archive, digest, root=root, mode_file=mode) == release_id
    assert (root / "previous").resolve() == root / "releases/old"
    assert (root / "current").resolve().name == release_id


@pytest.mark.parametrize("mutation", ["bytes", "mode", "hardlink", "cache-symlink", "destination-symlink"])
def test_existing_release_reuse_refuses_changes(release_installer, release_tree, tmp_path, mutation):
    installer, controller = release_installer
    root, mode = release_tree
    archive, digest, release_id = bundle(tmp_path)
    installer.install(archive, digest, root=root, mode_file=mode)
    destination = root / "releases" / release_id
    controller.replace_release_link(root, "current", root / "releases/old")
    launcher = destination / "src/toddlerbox/launcher.py"
    if mutation == "bytes":
        launcher.write_bytes(b"changed")
    elif mutation == "mode":
        launcher.chmod(0o666)
    elif mutation == "hardlink":
        (destination / "extra").hardlink_to(launcher)
    elif mutation == "cache-symlink":
        (destination / "__pycache__").symlink_to(tmp_path)
    else:
        destination.rename(root / "releases/moved")
        destination.symlink_to(root / "releases/moved")
    with pytest.raises(ValueError, match="differs|Hardlinked|Unsafe"):
        installer.install(archive, digest, root=root, mode_file=mode)
    assert (root / "current").resolve() == root / "releases/old"
# Build layout remains compatible with the unchanged resident installer.

def normalizer():
    path = Path(__file__).parents[1] / "system/normalize_venv.py"
    spec = importlib.util.spec_from_file_location("normalize_venv", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.normalize


def layout(tmp_path):
    release = tmp_path / "0123456789abcdef"
    binary = release / ".venv/bin"
    binary.mkdir(parents=True)
    (binary / "python").symlink_to("/usr/bin/python3")
    for name in ("python3", "python3.12"):
        (binary / name).symlink_to("python")
    return release, binary


def test_normalized_bundle_installs_with_resident_guards(release_installer, release_tree, tmp_path):
    release, binary = layout(tmp_path)
    (release / "src/toddlerbox").mkdir(parents=True)
    (release / "src/toddlerbox/launcher.py").write_text("# synthetic\n")
    (release / "uv.lock").write_text("# synthetic\n")
    (release / "data-schema.json").write_text('{"version":1,"typing":1,"paint":1}')
    # Reproduce the real failure before applying the build normalization.
    archive = tmp_path / "before.tar.gz"
    with tarfile.open(archive, "w:gz") as target:
        target.add(release, arcname=release.name)
    installer, _ = release_installer
    root, mode = release_tree
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(tarfile.LinkOutsideDestinationError):
        installer.install(archive, digest, root=root, mode_file=mode)
    assert (root / "current").resolve().name == "old"
    normalizer()(release / ".venv")
    archive = tmp_path / "after.tar.gz"
    with tarfile.open(archive, "w:gz") as target:
        target.add(release, arcname=release.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert installer.install(archive, digest, root=root, mode_file=mode) == release.name
    assert (binary / "python").is_symlink()
    assert not (binary / "python3").exists()


@pytest.mark.parametrize("unexpected", ["alias", "canonical", "entrypoint"])
def test_unexpected_links_or_entrypoints_fail_before_removal(tmp_path, unexpected):
    release, binary = layout(tmp_path)
    if unexpected == "entrypoint":
        (binary / "tool").write_text(f"#!{binary}/python3.12\n")
    else:
        link = binary / ("python3" if unexpected == "alias" else "python")
        link.unlink()
        link.symlink_to("/private/unexpected")
    with pytest.raises(ValueError):
        normalizer()(release / ".venv")
    assert (binary / "python3").is_symlink()
