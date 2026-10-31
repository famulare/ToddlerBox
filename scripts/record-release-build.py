"""Record checksums and pinned inputs for exact, synthetic-only CI build outputs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def record(directory):
    spec = importlib.util.spec_from_file_location('build_source_id', ROOT / 'system/source-id.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    revision = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    content = module.source_id(ROOT)
    assert (directory / 'release-id').read_text().strip() == content
    manifest = json.loads((directory / 'ToddlerBox-update.pyz.source.json').read_text())
    assert manifest['source'] == {'git': revision, 'content': content}
    app_name = f'toddlerbox-app-{content}.tar.gz'
    assert sha(directory / app_name) == manifest['app']
    files = {}
    for name in ['toddlerbox-installer.iso', 'ToddlerBox-update.pyz', app_name, 'packages.tsv', 'release-id']:
        path = directory / name
        assert path.is_file() and not path.is_symlink()
        files[name] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
    value = {'format': 1, 'version': tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version'],
             'sequence': int((ROOT / 'system/release-sequence').read_text()),
             'source': manifest['source'], 'platform': 'ubuntu24.04-x86_64',
             'files': files, 'qualification_status': 'pending; separate workflow results required',
             'python': sys.version, 'uv': subprocess.check_output(['uv', '--version'], text=True).strip(),
             'pinned_inputs': {'versions_env': (ROOT / 'system/versions.env').read_text(),
                               'uv_lock_sha256': sha(ROOT / 'uv.lock')},
             'commands': ['./system/build-compact.sh',
                          'uv run --frozen python system/build-update.py --cage build/dev/toddlerbox-cage --app build/dev/' + app_name + ' --output build/dev/ToddlerBox-update.pyz']}
    path = directory / 'build-record.json'
    path.write_text(json.dumps(value, indent=2) + '\n')
    checksums = ''.join(f"{entry['sha256']}  {name}\n" for name, entry in files.items())
    (directory / 'BUILD-SHA256SUMS').write_text(checksums + sha(path) + '  build-record.json\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    record(parser.parse_args().directory)
