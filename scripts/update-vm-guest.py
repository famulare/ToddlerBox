"""Synthetic-only guest checks; never installed in a ToddlerBox image.

Fault hooks wrap the installed updater in this process, after real durable
writes. They stop the process; the host must issue a real QMP reset. No status
is fabricated and no production source file is patched.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import stat
import struct
import sys
import zlib

sys.path.insert(0, '/usr/local/lib/toddlerbox-system')
QA = Path('/root/update-qa')
ROOT = Path('/')
BOUNDARIES = ('applying', 'system-replaced', 'pending', 'restoring')


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def record(name, value):
    from boot_recovery import atomic
    atomic(QA / name, (json.dumps(value, sort_keys=True) + '\n').encode())


def seed():
    QA.mkdir(mode=0o700)
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>2I5B', 4, 3, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress((b'\0' + b'\x0a\x46\xb4' * 4) * 3))
    png += chunk(b'IEND', b'')
    text = 'synthetic durable work'
    document = {'version': 1, 'rich_lines': [[{'char': char, 'size': 48, 'style': 'plain'} for char in text]],
                'cursor': [0, len(text)], 'size': 48, 'style': 'plain'}
    files = {'paint/qa-preserved.png': png,
             'typing/archive/qa-preserved.json': (json.dumps(document) + '\n').encode()}
    import pwd
    user = pwd.getpwnam('toddlerbox')
    for relative, data in files.items():
        path = Path('/var/lib/toddlerbox') / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        for parent in (path.parent, *path.parent.parents):
            if parent == Path('/var/lib/toddlerbox').parent:
                break
            os.chown(parent, user.pw_uid, user.pw_gid)
        path.write_bytes(data)
        os.chown(path, user.pw_uid, user.pw_gid)
    paths = [Path('/var/lib/toddlerbox') / name for name in files]
    paths.append(Path('/etc/toddlerbox/config.yaml'))
    # Class C must remain the original installer's resident code/configuration.
    for name in ('usr/local/lib/toddlerbox-system/boot_recovery.py',
                 'usr/local/sbin/toddlerbox-firstboot',
                 'etc/sysctl.d/90-toddlerbox.conf', 'etc/default/grub.d/toddlerbox.cfg'):
        if (ROOT / name).is_file():
            paths.append(ROOT / name)
    paths.extend(p for p in Path('/usr/local/lib/toddlerbox-system/tbx_sync').rglob('*')
                 if p.is_file() and p.suffix != '.pyc')
    record('preserved.json', {str(p): digest(p) for p in paths})
    (QA / 'original-public-key.pem').write_bytes(Path('/etc/toddlerbox/release-public-key.pem').read_bytes())
    check_preserved()


def check_preserved():
    for name, expected in json.loads((QA / 'preserved.json').read_text()).items():
        assert digest(Path(name)) == expected, 'Preserved synthetic data/config/resident file changed'
    assert not Path('/var/lib/toddlerbox-system/recovery-error').exists(), 'Resident recovery failed'


def pair():
    from update_bundle import FILES, app_links
    return {'files': {name: [digest(ROOT / path), stat.S_IMODE((ROOT / path).stat().st_mode)]
                      if (ROOT / path).exists() else None for name, (path, _) in FILES.items()},
            'links': app_links(ROOT)}


def inject_key():
    from boot_recovery import atomic
    original = (QA / 'original-public-key.pem').read_bytes()
    public = Path('/qa/vm-public-key.pem').read_bytes()
    atomic(Path('/etc/toddlerbox/release-public-key.pem'), original.rstrip() + b'\n' + public, 0o644)


def verify_release(directory, sequence):
    from release_client import verify
    value = verify((directory / 'stable.json').read_bytes(), (directory / 'stable.json.sig').read_bytes(),
                   Path('/etc/toddlerbox/release-public-key.pem').read_bytes())
    assert value['sequence'] == sequence, 'Unexpected signed sequence'
    expected_tag = 'vm-dev-' + value['source'] if directory.name == 'candidate' else directory.name
    assert value['tag'] == expected_tag, 'Unexpected signed release tag'
    assert (directory / 'ToddlerBox-update.pyz').stat().st_size == value['bytes']
    assert digest(directory / 'ToddlerBox-update.pyz') == value['sha256']
    return value


def install(directory, sequence, boundary=None):
    import update_bundle
    from release_client import sequence_guard
    from boot_recovery import record as durable_record
    value = verify_release(directory, sequence)
    sequence_guard(value['sequence'], ROOT, source=value['source'], digest=value['sha256'])
    # Production catalogue floor update using locally supplied verified metadata.
    durable_record(Path('/var/lib/toddlerbox-system/release-sequence.json'),
                   {'sequence': value['sequence'], 'source': value['source'], 'sha256': value['sha256']})
    if boundary:
        arm_boundary(update_bundle, boundary)
    print(update_bundle.run(directory / 'ToddlerBox-update.pyz', value['sha256'],
                            release_sequence=value['sequence'], release_source=value['source']), flush=True)


def stop_at(boundary):
    from boot_recovery import latest
    job, state = latest(ROOT)
    assert state['status'] == ('restoring' if boundary == 'restoring' else
                               'pending' if boundary == 'pending' else 'applying')
    record('boundary.json', {'boundary': boundary, 'status': state['status'], 'pid': os.getpid(),
                             'source': state['source']['content'], 'job': job.name})
    os.sync()
    os.kill(os.getpid(), signal.SIGSTOP)
    raise AssertionError('Stopped updater must be reset, never resumed')


def arm_boundary(updater, boundary):
    if boundary not in BOUNDARIES:
        raise ValueError('Unknown interruption boundary')
    original_record, original_replace = updater.record, updater.replace

    def observed_record(path, value):
        original_record(path, value)
        if boundary == 'applying' and path.name == 'latest.json':
            stop_at(boundary)
        if boundary == 'pending' and path.name == 'state.json' and value.get('status') == 'pending':
            stop_at(boundary)

    def observed_replace(source, target, mode):
        original_replace(source, target, mode)
        if boundary == 'system-replaced' and target == ROOT / 'usr/local/sbin/toddlerbox-install-release':
            stop_at(boundary)

    updater.record, updater.replace = observed_record, observed_replace
    if boundary == 'restoring':
        import boot_recovery
        original_atomic = boot_recovery.atomic

        def observed_atomic(path, content, mode=0o600):
            original_atomic(path, content, mode)
            if path == ROOT / 'usr/local/sbin/toddlerbox-install-release':
                stop_at(boundary)
        boot_recovery.atomic = observed_atomic


def check_boundary(expected, source=None):
    from boot_recovery import latest
    value = json.loads((QA / 'boundary.json').read_text())
    assert value['boundary'] == expected
    if source:
        assert value['source'] == source, 'Interruption belongs to another candidate'
    process = Path(f'/proc/{value["pid"]}/status').read_text()
    assert any(line.startswith('State:') and line.split()[1] == 'T' for line in process.splitlines())
    job, state = latest(ROOT)
    assert state['status'] == value['status'] and job.name == value['job']
    assert state['source']['content'] == value['source']
    print(json.dumps({'boundary': expected, 'durable_status': state['status'], 'stopped': True}))


def check_version(version, source=None, status=None):
    assert importlib.metadata.version('ToddlerBox') == version, 'Unexpected installed version'
    if source:
        assert Path('/opt/toddlerbox/current').resolve().name == source, 'Unexpected source identity'
    if status:
        from boot_recovery import latest
        assert latest(ROOT)[1]['status'] == status, 'Unexpected durable journal status'
    check_preserved()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('seed', 'preserved', 'inject-key', 'save-pair', 'check-pair',
                                    'install', 'rollback', 'boundary', 'version', 'untrusted'))
    p.add_argument('--directory', type=Path)
    p.add_argument('--sequence', type=int)
    p.add_argument('--boundary', choices=BOUNDARIES)
    p.add_argument('--version')
    p.add_argument('--source')
    p.add_argument('--status')
    a = p.parse_args()
    assert os.geteuid() == 0, 'Disposable guest root only'
    if a.action == 'seed': seed()
    elif a.action == 'preserved': check_preserved()
    elif a.action == 'inject-key': inject_key()
    elif a.action == 'save-pair': record('pair.json', pair())
    elif a.action == 'check-pair':
        assert pair() == json.loads((QA / 'pair.json').read_text()), 'Known-good system/app pair changed'
        check_preserved()
    elif a.action == 'install': install(a.directory, a.sequence, a.boundary)
    elif a.action == 'rollback':
        import update_bundle
        if a.boundary: arm_boundary(update_bundle, a.boundary)
        print(update_bundle.run(rollback=True), flush=True)
    elif a.action == 'boundary': check_boundary(a.boundary, a.source)
    elif a.action == 'version': check_version(a.version, a.source, a.status)
    elif a.action == 'untrusted':
        try: verify_release(a.directory, a.sequence)
        except ValueError as error:
            assert 'signature' in str(error).lower()
        else: raise AssertionError('VM signature unexpectedly trusted before key injection')


if __name__ == '__main__': main()
