"""Synthetic removable-media setup, integrity failures and conservative repeats."""
import errno
import hashlib
import json
import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
from sync_fixtures import package, paths, png, typing
from system.tbx_sync import usb_setup as usb
from system.tbx_sync.state import load
ORIGINAL_PARENT_INSTALL = usb.parent_install


@pytest.fixture(autouse=True)
def unprivileged_fixture_install(monkeypatch):
    monkeypatch.setattr(usb, 'parent_install', nullcontext)


@pytest.fixture
def transfer(tmp_path):
    mount = tmp_path / 'TEST_USB'
    mount.mkdir()
    archive, digest = package(mount)
    sidecar = archive.with_name(archive.name + '.sha256')
    sidecar.write_text(f'{digest}  {archive.name}\n')
    return mount, archive, digest, sidecar


def test_discovery_accepts_both_names_but_never_linked_files(transfer):
    mount, archive, _, _ = transfer
    dated = mount / 'toddlerbox-setup-2026-10-09.tar.gz'
    dated.write_bytes(archive.read_bytes())
    (mount / 'linked.toddlerbox-setup.tar.gz').symlink_to(archive)
    other = mount / 'hardlink.toddlerbox-setup.tar.gz'
    other.hardlink_to(dated)
    (mount / 'ordinary.tar.gz').write_bytes(b'not setup')
    assert [x.name for x in usb.discover([mount])] == [archive.name]
    other.unlink()
    assert {x.name for x in usb.discover([mount])} == {archive.name, dated.name}


def test_only_usb_or_removable_mounts_under_media_are_discovered(monkeypatch):
    devices = {'blockdevices':[
        {'tran':'usb','rm':False,'mountpoints':[None], 'children':[
            {'mountpoints':['/media/parent/USB'], 'rm':False}]},
        {'tran':'sata','rm':False,'mountpoints':['/media/parent/INTERNAL']},
        {'tran':'sata','rm':True,'mountpoints':['/run/media/parent/SD']},
        {'tran':'usb','rm':True,'mountpoints':['/','/private']}]}
    monkeypatch.setattr(usb.subprocess, 'run', lambda args, **kw: SimpleNamespace(stdout=json.dumps(devices)))
    assert usb.usb_mounts() == [Path('/media/parent/USB'), Path('/run/media/parent/SD')]


@pytest.mark.parametrize('text', ['0'*64, 'A'*64+'  package.tar.gz', 'a'*64+' *package.tar.gz'])
def test_plain_and_sha256sum_checksum_forms(text):
    assert usb.checksum((text+'\n').encode(), 'package.tar.gz') == text[:64].lower()


@pytest.mark.parametrize('text', ['', 'short', 'z'*64, 'a'*64+'  wrong.tar.gz',
                                  'a'*64+'  ../package.tar.gz', 'a'*64+'  /etc/shadow',
                                  'a'*64+'\n'+'b'*64, 'a'*64+'  package.tar.gz\n'+ 'a'*64])
def test_invalid_ambiguous_or_redirecting_checksum_refused(text):
    with pytest.raises(usb.Refused):
        usb.checksum(text.encode(), 'package.tar.gz')


def test_single_package_flow_requires_no_path_or_hash_and_preserves_repeated_work(transfer, tmp_path):
    mount, archive, digest, sidecar = transfer
    locations = paths(tmp_path / 'device')
    current = locations.data / 'typing/current.json'
    current.write_bytes(typing('new child work'))
    original, checksum = archive.read_bytes(), sidecar.read_bytes()
    questions, messages = [], []
    def ask(prompt):
        questions.append(prompt)
        return 'y'
    result = usb.flow(locations, find=lambda:usb.discover([mount]), ask=ask, tell=messages.append, minimum=0)
    assert result == {'result':'installed','photos_imported':1}
    assert len(questions) == 1 and 'Install' in questions[0]
    assert any('Success. 1 new photos' in text for text in messages)
    assert any(digest in text for text in messages)
    assert load(locations.state / 'setup-receipt.json')['package_sha256'] == digest
    (locations.library / 'example.png').write_bytes(png('purple'))
    result = usb.flow(locations, find=lambda:usb.discover([mount]), ask=ask, tell=messages.append, minimum=0)
    assert result == {'result':'already-installed','photos_imported':0}
    assert any('Already installed' in text for text in messages)
    assert (locations.library / 'example.png').read_bytes() == png('purple')
    assert current.read_bytes() == typing('new child work')
    assert archive.read_bytes() == original and sidecar.read_bytes() == checksum


def test_multiple_packages_require_selection_or_cancel(transfer, tmp_path):
    mount, archive, _, _ = transfer
    other = mount / 'second.toddlerbox-setup.tar.gz'
    other.write_bytes(archive.read_bytes())
    other.with_name(other.name+'.sha256').write_text(hashlib.sha256(other.read_bytes()).hexdigest())
    questions = []
    def ask(prompt):
        questions.append(prompt)
        return ''
    locations = paths(tmp_path / 'device')
    assert usb.flow(locations, find=lambda:usb.discover([mount]), ask=ask, tell=lambda _:None) is None
    assert len(questions) == 1 and 'Choose' in questions[0]
    assert not (locations.config / 'installed.json').exists()
    answers = iter(['2', 'y'])
    assert usb.flow(locations, find=lambda:usb.discover([mount]), ask=lambda _:next(answers),
                    tell=lambda _:None, minimum=0)['result'] == 'installed'


@pytest.mark.parametrize('failure', ['missing', 'wrong', 'mismatch'])
def test_bad_sidecar_never_calls_importer(transfer, tmp_path, monkeypatch, failure):
    mount, _, _, sidecar = transfer
    if failure == 'missing':
        sidecar.unlink()
    else:
        sidecar.write_text('a'*64 + ('  another.tar.gz' if failure == 'mismatch' else ''))
    monkeypatch.setattr(usb, 'setup', lambda *a, **k: pytest.fail('Unverified import'))
    with pytest.raises((OSError, usb.Refused)):
        usb.flow(paths(tmp_path/'device'), find=lambda:usb.discover([mount]),
                 ask=lambda _:'y', tell=lambda _:None, minimum=0)


@pytest.mark.parametrize('change', ['mutation', 'replacement', 'checksum', 'removal', 'full'])
def test_transfer_races_and_disk_full_refused_before_import(transfer, tmp_path, monkeypatch, change):
    mount, archive, _, sidecar = transfer
    candidate = usb.discover([mount])[0]
    directory = tmp_path / 'stage'
    directory.mkdir()
    def reserve(*args):
        if change == 'mutation':
            archive.write_bytes(archive.read_bytes()+b'changed')
        elif change == 'replacement':
            data = archive.read_bytes()
            archive.unlink()
            archive.write_bytes(data)
        elif change == 'checksum':
            sidecar.write_text('b'*64)
        elif change == 'removal':
            mount.rename(mount.with_name('unmounted'))
            mount.mkdir()
        else:
            raise OSError(errno.ENOSPC, 'synthetic disk full')
    monkeypatch.setattr(usb, 'reserve', reserve)
    with pytest.raises((OSError, usb.Refused)):
        usb.snapshot(candidate, directory, minimum=0)


def test_source_changes_after_verified_snapshot_cannot_change_import_inputs(transfer, tmp_path, monkeypatch):
    mount, archive, _, _ = transfer
    original_setup = usb.setup
    def install(locations, stable, digest, **kwargs):
        archive.write_bytes(b'changed after stable verification')
        assert hashlib.sha256(stable.read_bytes()).hexdigest() == digest
        return original_setup(locations, stable, digest, **kwargs)
    monkeypatch.setattr(usb, 'setup', install)
    locations = paths(tmp_path/'device')
    assert usb.flow(locations, find=lambda:usb.discover([mount]), ask=lambda _:'y',
                    tell=lambda _:None, minimum=0)['photos_imported'] == 1
    assert (locations.library/'example.png').read_bytes() == png()


def test_visible_failure_remains_until_dismissed_without_private_error_text(monkeypatch, capsys):
    import sys
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'system'))
    import appliance
    monkeypatch.setattr(appliance, 'guard', lambda:None)
    def fail(*a, **k):
        raise ValueError('synthetic secret token must never appear')
    monkeypatch.setattr(usb, 'flow', fail)
    prompts = []
    monkeypatch.setattr('builtins.input', lambda prompt:prompts.append(prompt) or '')
    assert usb.main() == 1
    assert prompts == ['Press Enter to close.']
    assert 'secret token' not in capsys.readouterr().out


def test_sidecar_symlink_to_private_file_is_refused(transfer, tmp_path):
    mount, _, _, sidecar = transfer
    private = tmp_path/'private'
    private.write_text('private sentinel')
    sidecar.unlink()
    sidecar.symlink_to(private)
    stage = tmp_path/'stage'
    stage.mkdir()
    with pytest.raises(OSError):
        usb.snapshot(usb.discover([mount])[0], stage, minimum=0)
    assert private.read_text() == 'private sentinel'


def test_final_parent_guard_runs_inside_maintenance_lock(monkeypatch):
    from contextlib import contextmanager
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'system'))
    import appliance
    events = []
    @contextmanager
    def lock():
        events.append('lock')
        yield
        events.append('unlock')
    monkeypatch.setattr(appliance, 'maintenance_lock', lock)
    monkeypatch.setattr(appliance, 'guard', lambda:events.append('guard'))
    with ORIGINAL_PARENT_INSTALL():
        events.append('install')
    assert events == ['lock','guard','install','unlock']


def test_sync_status_exposes_setup_receipt_without_claiming_a_sync(transfer, tmp_path, monkeypatch):
    from system.tbx_sync import cli
    mount, _, digest, _ = transfer
    locations = paths(tmp_path/'device')
    usb.flow(locations, find=lambda:usb.discover([mount]), ask=lambda _:'y', tell=lambda _:None, minimum=0)
    monkeypatch.setattr(cli, 'service_state', lambda:{'ActiveState':'inactive'})
    status = cli.status(locations)
    assert status['state'] == 'never-run'
    assert status['last_setup']['result'] == 'installed'
    assert status['last_setup']['photos_imported'] == 1
    assert status['last_setup']['package_sha256'] == digest
