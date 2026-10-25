"""The old updater omits --journaled; authenticate it without opening direct installs."""
import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_appliance import appliance_machine, modules  # noqa: F401
from test_update_bundle import updater, machine, make_bundle  # noqa: F401
from test_system_release import release_installer, release_tree, bundle  # noqa: F401


@pytest.fixture
def parent_proof(release_installer, tmp_path, monkeypatch):
    installer, _ = release_installer
    state = tmp_path / 'state'
    (state / 'updates').mkdir(parents=True)
    lock = state / 'updates/lock'
    lock.touch()
    pid = os.getppid()
    proc = tmp_path / 'proc' / str(pid)
    (proc / 'fdinfo').mkdir(parents=True)
    (proc / 'status').write_text('Uid:\t0\t0\t0\t0\n')
    st = lock.stat()
    entry = proc / 'fdinfo/3'
    entry.write_text(f'lock:\t1: FLOCK ADVISORY WRITE {pid} {os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino} 0 EOF\n')
    real_path = Path
    monkeypatch.setattr(installer, 'Path', lambda path: tmp_path / 'proc' if path == '/proc' else real_path(path))
    monkeypatch.setattr(installer.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(installer.os, 'pidfd_open', lambda parent: os.open('/dev/null', os.O_RDONLY), raising=False)
    poller = SimpleNamespace(register=lambda *a: None, poll=lambda *a: [])
    monkeypatch.setattr(installer.select, 'poll', lambda: poller, raising=False)
    return installer, state, proc, entry, poller


def test_parent_proof_requires_exact_live_root_exclusive_kernel_lock(parent_proof):
    installer, state, _, _, _ = parent_proof
    assert installer.parent_update_lock(state)


@pytest.mark.parametrize('fault', ['non-root', 'wrong-pid', 'wrong-inode', 'read-lock', 'waiting', 'dead', 'missing', 'oversized'])
def test_busy_lock_or_planted_marker_cannot_authenticate_an_unrelated_parent(parent_proof, fault):
    installer, state, proc, entry, poller = parent_proof
    if fault == 'non-root': (proc / 'status').write_text('Uid:\t0\t1000\t0\t0\n')
    if fault == 'wrong-pid': entry.write_text(entry.read_text().replace(f'WRITE {os.getppid()} ', 'WRITE 999999 '))
    if fault == 'wrong-inode': entry.write_text(entry.read_text().replace(f':{(state / "updates/lock").stat().st_ino} ', ':999999 '))
    if fault == 'read-lock': entry.write_text(entry.read_text().replace('WRITE', 'READ'))
    if fault == 'waiting': entry.write_text(entry.read_text().replace('FLOCK', '-> FLOCK'))
    if fault == 'dead': poller.poll = lambda *a: [(1, 1)]
    if fault == 'missing': entry.unlink()
    if fault == 'oversized': entry.write_text(entry.read_text() + 'x' * 16385)
    assert not installer.parent_update_lock(state)


def test_legacy_journal_requires_matching_staged_bytes_and_source(appliance_machine, updater, modules,
                                                                release_installer, tmp_path, monkeypatch):
    installer, _ = release_installer
    module, _ = updater
    root = appliance_machine
    state = root / 'var/lib/toddlerbox-system'
    app, app_digest, release_id = bundle(tmp_path)
    archive, digest = make_bundle(tmp_path, module, app=True)
    import zipfile
    with zipfile.ZipFile(archive) as inp: data = {name: inp.read(name) for name in inp.namelist()}
    manifest = json.loads(data['manifest.json'])
    manifest['source']['content'] = release_id
    manifest['app'] = app_digest
    data.update({'app.tar.gz': app.read_bytes(), 'manifest.json': json.dumps(manifest).encode()})
    with zipfile.ZipFile(archive, 'w') as out:
        for name, value in data.items(): out.writestr(name, value)
    monkeypatch.setattr(installer, 'parent_update_lock', lambda path: True)
    original = installer.legacy_journaled_parent
    monkeypatch.setattr(installer, 'legacy_journaled_parent',
                        lambda path, expected, directory: original(path, expected, directory, root=root))
    called = []
    def invoke(args):
        if 'toddlerbox-install-release' in args[0]:
            # Published updater's exact argument shape: no --journaled flag.
            staged = Path(args[1])
            assert not original(staged, '0' * 64, state, root=root)
            assert not original(app, args[2], state, root=root)
            assert installer.install(staged, args[2], root=root / 'opt/toddlerbox',
                                     mode_file=root / 'run/toddlerbox-system/mode', state=state) == release_id
            called.append(True)
    monkeypatch.setattr(module, 'command', invoke)
    module.run(archive, module.sha(archive), root=root, unsigned_recovery=True)
    assert called == [True]
    assert (root / 'opt/toddlerbox/current').resolve().name == release_id


def test_macos_missing_linux_identity_support_fails_closed(release_installer, tmp_path, monkeypatch):
    installer, _ = release_installer
    monkeypatch.setattr(installer.os, 'geteuid', lambda: 0)
    monkeypatch.delattr(installer.os, 'pidfd_open', raising=False)
    assert not installer.parent_update_lock(tmp_path)
