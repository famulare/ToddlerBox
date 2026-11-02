"""Retained build reuse never claims prior qualification or permits changed bytes."""
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).parents[1]


@pytest.fixture
def reuse():
    spec = importlib.util.spec_from_file_location('retained_installer', ROOT / 'scripts/reuse-installer-candidate.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def provenance(reuse):
    record = {'run_id': 123, 'git': 'a'*40, 'content': 'b'*16,
              'bundle_sha256': 'c'*64, 'installer_sha256': 'd'*64, 'artifact_id': 456, 'artifact_sha256': 'e'*64}
    run = {'head_sha': record['git'], 'status': 'completed', 'path': '.github/workflows/dev-vm-qualify.yml',
           'head_branch': 'dev/test', 'repository': {'full_name': 'famulare/ToddlerBox'}}
    jobs = {'jobs': [{'name': 'fresh-install', 'status': 'completed', 'conclusion': 'failure',
                     'steps': [{'name': name, 'conclusion': 'success'} for name in reuse.BUILD_STEPS] +
                              [{'name': 'Qualify fresh installation without networking', 'conclusion': 'failure'}]}]}
    return record, run, jobs


def test_completed_build_can_be_requalified_after_a_later_harness_failure(reuse, provenance):
    reuse.validate(*provenance)


@pytest.mark.parametrize('fault', ['git', 'workflow', 'repository', 'branch', 'running', 'hash', 'build', 'record', 'retention'])
def test_retained_build_provenance_refuses_unverified_inputs(reuse, provenance, fault):
    record, run, jobs = provenance
    if fault == 'git': run['head_sha'] = 'f'*40
    if fault == 'workflow': run['path'] = 'other.yml'
    if fault == 'repository': run['repository']['full_name'] = 'other/repo'
    if fault == 'branch': run['head_branch'] = 'main'
    if fault == 'running': run['status'] = 'in_progress'
    if fault == 'hash': record['artifact_sha256'] = 'bad'
    if fault in {'build', 'record', 'retention'}:
        word = {'build': 'Build disk', 'record': 'Record and retain', 'retention': 'Preserve exact'}[fault]
        for step in jobs['jobs'][0]['steps']:
            if step['name'].startswith(word): step['conclusion'] = 'failure'
    with pytest.raises(ValueError): reuse.validate(record, run, jobs)


@pytest.fixture
def retained(reuse, tmp_path, monkeypatch):
    (tmp_path/'system').mkdir()
    source = tmp_path/'system/source-id.py'
    source.write_text("def source_id(root): return '" + 'b'*16 + "'\n")
    monkeypatch.setattr(reuse, 'ROOT', tmp_path)
    out = tmp_path/'outputs';out.mkdir()
    record = {'git': 'a'*40, 'content': 'b'*16}
    app = 'toddlerbox-app-' + record['content'] + '.tar.gz'
    for name in ['toddlerbox-installer.iso', app, 'packages.tsv', 'release-id']:
        (out/name).write_bytes(b'synthetic fixture')
    (out/'release-id').write_text(record['content']+'\n')
    manifest = {'source': dict(record), 'app': reuse.sha(out/app)}
    with zipfile.ZipFile(out/'ToddlerBox-update.pyz', 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
    files = {p.name: {'bytes': p.stat().st_size, 'sha256': reuse.sha(p)} for p in out.iterdir()}
    (out/'build-record.json').write_text(json.dumps({'source': dict(record), 'files': files}))
    for name, key in [('ToddlerBox-update.pyz', 'bundle_sha256'), ('toddlerbox-installer.iso', 'installer_sha256')]:
        record[key] = reuse.sha(out/name)
    return record, out, source


def test_exact_retained_bytes_and_source_are_checked_before_vm_creation(reuse, retained):
    record, out, source = retained
    reuse.check_files(record, out)
    (out/'toddlerbox-installer.iso').write_bytes(b'torn')
    with pytest.raises(ValueError, match='checksum'):reuse.check_files(record, out)


def test_runtime_changes_require_a_rebuild_even_when_installer_hash_matches(reuse, retained):
    record, out, source = retained
    source.write_text("def source_id(root): return '" + 'f'*16 + "'\n")
    with pytest.raises(ValueError, match='Runtime changed'):reuse.check_files(record, out)


@pytest.mark.parametrize('fault', [None, 'archive-hash', 'traversal'])
def test_retry_archive_integrity_and_extraction_are_checked_before_use(reuse, retained, tmp_path, monkeypatch, fault):
    import sys
    record, out, source = retained
    record.update(run_id=123, artifact_id=456)
    (out/'ToddlerBox-update.pyz.source.json').write_text('{}')
    (out/'BUILD-SHA256SUMS').write_text('synthetic checksums')
    archive = tmp_path/'retained.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        for path in out.iterdir():z.write(path, path.name)
        if fault == 'traversal':z.writestr('../escape', b'bad')
    record['artifact_sha256'] = reuse.sha(archive) if fault != 'archive-hash' else '0'*64
    pin = tmp_path/'pin.json';pin.write_text(json.dumps(record))
    target = tmp_path/'new-output'
    monkeypatch.setattr(sys, 'argv', ['reuse', str(pin), '--archive', str(archive), '--directory', str(target)])
    if fault is None:
        reuse.main()
        assert reuse.sha(target/'toddlerbox-installer.iso') == record['installer_sha256']
    else:
        with pytest.raises(ValueError):reuse.main()
        assert not target.exists()
    assert not (tmp_path/'escape').exists()
