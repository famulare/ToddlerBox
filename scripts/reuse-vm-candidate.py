"""Verify a prior dev build before a harness-only update qualification retry.

Reads only public run metadata/artifacts. No release, tag or production trust
state is changed. The main harness separately requires identical source bytes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile


def validate(record, run, jobs):
    if (not isinstance(record, dict) or set(record) != {'run_id', 'git', 'content', 'sha256'}
            or type(record['run_id']) is not int
            or not 1 <= record['run_id'] < 2 ** 63
            or not all(isinstance(record[key], str) for key in ('git', 'content', 'sha256'))
            or not re.fullmatch(r'[0-9a-f]{40}', record['git'])
            or not re.fullmatch(r'[0-9a-f]{16}', record['content'])
            or not re.fullmatch(r'[0-9a-f]{64}', record['sha256'])):
        raise ValueError('Invalid pinned candidate record')
    if (run['head_sha'] != record['git'] or run['status'] != 'completed'
            or run['path'] != '.github/workflows/dev-vm-qualify.yml'
            or not run['head_branch'].startswith('dev/')
            or run['repository']['full_name'] != 'famulare/ToddlerBox'):
        raise ValueError('Candidate run does not match the pinned dev build')
    if not any(job['name'] == 'fresh-install' and job['conclusion'] == 'success'
               and job['status'] == 'completed' for job in jobs['jobs']):
        raise ValueError('Candidate has no successful fresh-install qualification')


def check_bundle(record, bundle):
    with bundle.open('rb') as handle:
        if hashlib.file_digest(handle, 'sha256').hexdigest() != record['sha256']:
            raise ValueError('Downloaded candidate checksum mismatch')
    with zipfile.ZipFile(bundle) as archive:
        if archive.getinfo('manifest.json').file_size > 16384:
            raise ValueError('Oversized candidate manifest')
        source = json.loads(archive.read('manifest.json'))['source']
    if source != {'git': record['git'], 'content': record['content']}:
        raise ValueError('Downloaded candidate source mismatch')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('record', type=Path)
    p.add_argument('--github-output', type=Path)
    p.add_argument('--bundle', type=Path)
    args = p.parse_args()
    record = json.loads(args.record.read_text())
    if args.bundle:
        check_bundle(record, args.bundle)
        return
    run_id = record.get('run_id')
    if type(run_id) is not int or not 1 <= run_id < 2 ** 63:
        raise ValueError('Invalid pinned run ID')
    def api(suffix):
        return json.loads(subprocess.check_output(['gh', 'api',
            f'repos/famulare/ToddlerBox/actions/runs/{run_id}' + suffix], text=True))
    validate(record, api(''), api('/jobs?per_page=100'))
    if args.github_output:
        with args.github_output.open('a') as handle:
            for key in ('run_id', 'git', 'content', 'sha256'):
                handle.write(f'{key}={record[key]}\n')
    print(f'Pinned dev candidate: run {run_id}, source {record["git"]}, SHA-256 {record["sha256"]}')


if __name__ == '__main__': main()
