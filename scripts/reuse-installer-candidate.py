"""Retry fresh qualification of exact retained bytes after a harness-only fix.

Requires a completed successful build/retention stage, not a successful previous
qualification. It never marks a failed qualification passed. Runtime content must
match; the fresh-install job then reruns every check before update-chain starts.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD_STEPS = {'Build disk, installer and unsigned update bundle',
               'Record and retain exact release preparation outputs',
               'Preserve exact installer and build provenance'}


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def validate_record(record):
    if (set(record) != {'run_id', 'git', 'content', 'bundle_sha256', 'installer_sha256', 'artifact_id', 'artifact_sha256'}
            or type(record['run_id']) is not int or not 1 <= record['run_id'] < 2**63
            or type(record['artifact_id']) is not int or not 1 <= record['artifact_id'] < 2**63
            or any(not isinstance(record[k], str) or not re.fullmatch(r'[0-9a-f]{' + str(n) + '}', record[k])
                   for k, n in [('git', 40), ('content', 16), ('bundle_sha256', 64), ('installer_sha256', 64), ('artifact_sha256', 64)])):
        raise ValueError('Invalid exact-installer record')


def validate(record, run, jobs):
    validate_record(record)
    if (run['head_sha'] != record['git'] or run['status'] != 'completed'
            or run['path'] != '.github/workflows/dev-vm-qualify.yml'
            or not run['head_branch'].startswith('dev/')
            or run['repository']['full_name'] != 'famulare/ToddlerBox'):
        raise ValueError('Unexpected retained-installer provenance')
    matches = [j for j in jobs['jobs'] if j['name'] == 'fresh-install' and j['status'] == 'completed']
    if len(matches) != 1:
        raise ValueError('Missing completed build job')
    passed = {s['name'] for s in matches[0]['steps'] if s['conclusion'] == 'success'}
    if not BUILD_STEPS <= passed:
        raise ValueError('Original build/record/retention did not all succeed')


def check_files(record, directory):
    for name, key in [('toddlerbox-installer.iso', 'installer_sha256'),
                      ('ToddlerBox-update.pyz', 'bundle_sha256')]:
        path = directory / name
        if path.is_symlink() or sha(path) != record[key]:
            raise ValueError('Retained artifact checksum mismatch')
    if (directory / 'release-id').read_text().strip() != record['content']:
        raise ValueError('Retained release identity mismatch')
    value = json.loads((directory / 'build-record.json').read_text())
    expected = {'git': record['git'], 'content': record['content']}
    if value['source'] != expected:
        raise ValueError('Retained build source mismatch')
    with zipfile.ZipFile(directory / 'ToddlerBox-update.pyz') as archive:
        if archive.getinfo('manifest.json').file_size > 16384:
            raise ValueError('Oversized bundle manifest')
        manifest = json.loads(archive.read('manifest.json'))
    if manifest['source'] != expected or manifest['app'] != sha(directory / f"toddlerbox-app-{record['content']}.tar.gz"):
        raise ValueError('Retained bundle/app source mismatch')
    for name, entry in value['files'].items():
        if name not in {'toddlerbox-installer.iso', 'ToddlerBox-update.pyz', 'packages.tsv', 'release-id', f"toddlerbox-app-{record['content']}.tar.gz"}:
            raise ValueError('Unexpected retained output')
        path = directory / name
        if path.is_symlink() or path.stat().st_size != entry['bytes'] or sha(path) != entry['sha256']:
            raise ValueError('Retained build output mismatch')
    spec = importlib.util.spec_from_file_location('installer_retry_source', ROOT / 'system/source-id.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.source_id(ROOT) != record['content']:
        raise ValueError('Runtime changed; rebuilding is required')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args()
    record = json.loads(args.record.read_text())
    validate_record(record)
    if args.directory:
        if args.archive:
            if sha(args.archive) != record['artifact_sha256']:
                raise ValueError('Retained archive checksum mismatch')
            expected = {'toddlerbox-installer.iso', 'ToddlerBox-update.pyz',
                        'ToddlerBox-update.pyz.source.json', 'build-record.json',
                        'BUILD-SHA256SUMS', 'packages.tsv', 'release-id',
                        f"toddlerbox-app-{record['content']}.tar.gz"}
            with zipfile.ZipFile(args.archive) as archive:
                entries = archive.infolist()
                if (len(entries) != len(expected) or {e.filename for e in entries} != expected
                        or any(e.file_size > 4*1024**3 or stat.S_ISLNK(e.external_attr >> 16) for e in entries)):
                    raise ValueError('Unexpected retained archive contents')
                args.directory.mkdir(parents=True, exist_ok=False)
                for entry in entries:
                    with archive.open(entry) as source, (args.directory/entry.filename).open('xb') as target:
                        shutil.copyfileobj(source, target)
        check_files(record, args.directory)
    else:
        # Validate scalar input before interpolating it in an API path.
        if type(record.get('run_id')) is not int or not 1 <= record['run_id'] < 2**63:
            raise ValueError('Invalid run ID')
        def api(suffix):
            return json.loads(subprocess.check_output(['gh', 'api', f"repos/famulare/ToddlerBox/actions/runs/{record['run_id']}" + suffix], text=True))
        validate(record, api(''), api('/jobs?per_page=100'))
        matches = [a for a in api('/artifacts')['artifacts'] if a['name'] == 'dev-installer-candidate']
        if (len(matches) != 1 or matches[0]['expired'] or matches[0]['id'] != record['artifact_id']
                or matches[0]['digest'] != 'sha256:' + record['artifact_sha256']):
            raise ValueError('Unexpected retained archive identity')
    if args.github_output:
        with args.github_output.open('a') as handle:
            for key in ['run_id', 'git', 'content', 'bundle_sha256', 'artifact_id']:
                handle.write(f'{key}={record[key]}\n')


if __name__ == '__main__':
    main()
