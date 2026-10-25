"""Qualification guards, signed identity and genuine updater fault boundaries."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from test_appliance import appliance_machine, modules  # noqa: F401
from test_update_bundle import updater, machine, make_bundle  # noqa: F401
from test_system_release import release_installer, release_tree, bundle  # noqa: F401

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness():
    return load('update_qa', ROOT / 'scripts/update_vm_qualification.py')


@pytest.fixture
def inputs(tmp_path, harness, monkeypatch):
    image, candidate, published = (tmp_path / name for name in ('image', 'candidate', 'published'))
    for directory in (image, candidate, published, tmp_path / 'build'):
        directory.mkdir()
    data = b'synthetic public ISO'
    (image / 'toddlerbox-installer.iso').write_bytes(data)
    (image / 'INSTALLER-SHA256SUMS').write_text(hashlib.sha256(data).hexdigest() + '  toddlerbox-installer.iso\n')
    with zipfile.ZipFile(candidate / 'ToddlerBox-update.pyz', 'w') as archive:
        archive.writestr('manifest.json', json.dumps({'source': {'git': 'a' * 40, 'content': 'b' * 16}, 'app': 'c' * 64}))
    monkeypatch.setattr(harness.subprocess, 'check_output', lambda *a, **k: 'a' * 40 + '\n')
    monkeypatch.setattr(harness, 'checkout_source', lambda root: 'b' * 16)
    args = harness.parse_args([str(candidate), str(tmp_path / 'build/responsive-update-vm-test'),
                              '--baseline-image-dir', str(image), '--baseline-version', '0.4.0',
                              '--baseline-sequence', '2', '--published-dir', str(published),
                              '--release', 'v0.5.0:0.5.0:3', '--release', 'v0.5.1:0.5.1:4',
                              '--candidate-version', '0.5.1', '--candidate-sequence', '5'])
    return args, tmp_path


def test_portable_inputs_validate_without_creating_or_opening_a_writable_disk(harness, inputs):
    args, root = inputs
    out, _, manifest = harness.validate_inputs(args, root)
    assert not out.exists()
    assert manifest['source']['git'] == 'a' * 40


@pytest.mark.parametrize('name', ['appliance-qualified', 'audio-polish', 'responsive-update-vm-existing'])
def test_protected_or_existing_output_is_refused_before_provisioning(harness, inputs, name):
    args, root = inputs
    args.output = root / 'build' / name
    args.output.mkdir()
    (args.output / 'preserve').write_bytes(b'checkpoint')
    with pytest.raises(ValueError): harness.validate_inputs(args, root)
    assert (args.output / 'preserve').read_bytes() == b'checkpoint'


def test_symlink_alias_cannot_open_a_qualified_checkpoint_writable(harness, inputs):
    args, root = inputs
    protected = root / 'build/appliance-qualified'
    protected.mkdir()
    args.output.symlink_to(protected, target_is_directory=True)
    with pytest.raises(ValueError): harness.validate_inputs(args, root)


@pytest.mark.parametrize('fault', ['checksum', 'duplicate', 'revision', 'content', 'sequence'])
def test_bad_inputs_fail_before_creating_output(harness, inputs, fault):
    args, root = inputs
    if fault == 'checksum': (args.baseline_image_dir / 'toddlerbox-installer.iso').write_bytes(b'torn')
    if fault == 'duplicate':
        path = args.baseline_image_dir / 'INSTALLER-SHA256SUMS'
        path.write_text(path.read_text() * 2)
    if fault == 'revision': harness.subprocess.check_output = lambda *a, **k: 'd' * 40
    if fault == 'content': harness.checkout_source = lambda root: 'd' * 16
    if fault == 'sequence': args.candidate_sequence = 4
    with pytest.raises(ValueError): harness.validate_inputs(args, root)
    assert not args.output.exists()


@pytest.mark.parametrize('text', ['../secret:0.5.1:4', 'v0.5.1:$(cmd):4', 'v0.5.1:0.5.1:-1', 'v0.5.1:0.5.1:no'])
def test_release_arguments_are_bounded_path_and_shell_safe(harness, text):
    with pytest.raises(argparse.ArgumentTypeError): harness.release_input(text)


def test_synthetic_signer_writes_only_public_material_and_authenticates_exact_bundle(harness, inputs, monkeypatch, modules):
    args, root = inputs
    args.release = []
    out, _, manifest = harness.validate_inputs(args, root)
    out.mkdir()
    (root / 'scripts').mkdir()
    (root / 'scripts/update-vm-guest.py').write_text('# synthetic guest\n')
    monkeypatch.setattr(harness, 'ROOT', root)
    share, value = harness.prepare_share(args, out, manifest)
    client = load('qa_release_client', ROOT / 'system/release_client.py')
    data = (share / 'candidate/stable.json').read_bytes()
    signature = (share / 'candidate/stable.json.sig').read_bytes()
    public = (share / 'vm-public-key.pem').read_bytes()
    assert client.verify(data, signature, public) == value
    assert value['sha256'] == harness.sha(args.candidate / 'ToddlerBox-update.pyz')
    with pytest.raises(ValueError, match='signature'):
        client.verify(data + b' ', signature, public)
    assert all(b'PRIVATE KEY' not in path.read_bytes() for path in share.rglob('*') if path.is_file())
    assert value['sequence'] == 5 and (ROOT / 'system/release-sequence').read_text().strip() == '4'


@pytest.mark.parametrize('boundary', ['applying', 'system-replaced', 'pending', 'restoring'])
def test_fault_hooks_observe_real_durable_writes_in_the_actual_updater(appliance_machine, updater, modules,
                                                                     tmp_path, monkeypatch, boundary):
    guest = load('guest_qa', ROOT / 'scripts/update-vm-guest.py')
    module, _ = updater
    recovery = modules[0]
    root = appliance_machine
    installed = root / 'usr/local/sbin/toddlerbox-install-release'
    installed.write_bytes(b'baseline-installer')
    installed.chmod(0o755)
    monkeypatch.setattr(recovery, 'atomic', recovery.atomic)
    archive, digest = make_bundle(tmp_path, module, files={'toddlerbox-install-release': b'candidate-installer',
                                                          'controller.py': b'candidate-controller'})
    monkeypatch.setattr(guest, 'ROOT', root)
    seen = []
    class Stopped(BaseException): pass
    def stop(label):
        job, state = recovery.latest(root)
        assert (job / 'state.json').is_file()
        if label in {'system-replaced', 'pending'}:
            assert (root / 'usr/local/sbin/toddlerbox-install-release').read_bytes() == b'candidate-installer'
        if label == 'restoring':
            assert (root / 'usr/local/sbin/toddlerbox-install-release').read_bytes() != b'candidate-installer'
        seen.append((label, state['status']))
        raise Stopped()
    monkeypatch.setattr(guest, 'stop_at', stop)
    if boundary == 'restoring':
        module.run(archive, digest, root=root, unsigned_recovery=True)
        guest.arm_boundary(module, boundary)
        with pytest.raises(Stopped): module.run(rollback=True, root=root)
    else:
        guest.arm_boundary(module, boundary)
        with pytest.raises(Stopped): module.run(archive, digest, root=root, unsigned_recovery=True)
    assert seen == [(boundary, 'restoring' if boundary == 'restoring' else
                    'pending' if boundary == 'pending' else 'applying')]


def test_optional_share_preserves_existing_qemu_arguments_when_absent(tmp_path, monkeypatch):
    common = load('qa_common', ROOT / 'scripts/qualify-release-vm.py')
    qa = common.Qualification(tmp_path / 'image', tmp_path / 'out')
    calls = []
    qa.docker = lambda *args, **kwargs: calls.append(args)
    qa.start()
    assert '-fsdev' not in calls[-1] and 'none' == calls[-1][calls[-1].index('-nic') + 1]
    qa.share = tmp_path / 'public-inputs'
    qa.start()
    assert f'{qa.share}:/qa:ro' in calls[-1]
    assert 'local,id=qa,path=/qa,security_model=none,readonly=on' in calls[-1]
    assert '--network=none' in calls[-1]


def test_vm_workflow_keeps_read_only_permissions_and_allowlisted_evidence():
    import subprocess
    import yaml
    workflow = yaml.load((ROOT / '.github/workflows/dev-vm-qualify.yml').read_text(), Loader=yaml.BaseLoader)
    assert workflow['permissions'] == {'contents': 'read'}
    job = workflow['jobs']['update-chain']
    assert job['needs'] == 'fresh-install'
    assert job['concurrency']['cancel-in-progress'] == 'false'
    for name in ('fresh-install', 'update-chain'):
        for step in workflow['jobs'][name]['steps']:
            if 'run' in step:
                subprocess.run(['bash', '-n'], input=step['run'], text=True, check=True)
    evidence = job['steps'][-1]['with']
    assert evidence['retention-days'] == '14'
    assert evidence['path'].split() == ['build/responsive-update-vm-dev/checkpoint-*.png',
                                        'build/responsive-update-vm-dev/results.json']
