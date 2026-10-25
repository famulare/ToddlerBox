"""Portable published-installer -> signed releases -> dev-candidate VM qualification.

The old qualify-patch-update.py invocation remains available for historical
checkpoints. This route uses only public inputs and a fresh disposable disk.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def checkout_source(root):
    spec = importlib.util.spec_from_file_location('qa_source_id', root / 'system/source-id.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.source_id(root)


def installer_digest(directory):
    matches = []
    for line in (directory / 'INSTALLER-SHA256SUMS').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64}) [ *](.+)', line)
        if match and match[2] == 'toddlerbox-installer.iso':
            matches.append(match[1])
    if len(matches) != 1 or sha(directory / 'toddlerbox-installer.iso') != matches[0]:
        raise ValueError('Published installer checksum mismatch or ambiguous checksum record')
    return matches[0]


def release_input(text):
    parts = text.split(':')
    if (len(parts) != 3 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', parts[0])
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', parts[1])):
        raise argparse.ArgumentTypeError('Use TAG:VERSION:SEQUENCE')
    try:
        sequence = int(parts[2])
    except ValueError:
        raise argparse.ArgumentTypeError('Release sequence must be positive') from None
    if not 1 <= sequence < 2 ** 63:
        raise argparse.ArgumentTypeError('Release sequence must be positive')
    return parts[0], parts[1], sequence


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('candidate', type=Path, help='Directory containing the built ToddlerBox-update.pyz')
    p.add_argument('output', type=Path, help='New build/responsive-update-vm-* directory')
    p.add_argument('--baseline-image-dir', type=Path, required=True,
                   help='Published installer ISO and INSTALLER-SHA256SUMS')
    p.add_argument('--baseline-version', required=True)
    p.add_argument('--baseline-sequence', type=int, required=True)
    p.add_argument('--published-dir', type=Path, required=True, help='One directory per published tag')
    p.add_argument('--release', action='append', type=release_input, default=[],
                   help='Ordered signed hop TAG:VERSION:SEQUENCE; repeatable')
    p.add_argument('--candidate-version', required=True)
    p.add_argument('--candidate-sequence', type=int, required=True, help='VM-only signed sequence')
    return p.parse_args(argv)


def validate_inputs(args, root=ROOT):
    out = args.output.resolve()
    if out.parent != (root / 'build').resolve() or not out.name.startswith('responsive-update-vm-'):
        raise ValueError('Output must be a disposable build/responsive-update-vm-* directory')
    if out.exists():
        raise ValueError('Use a new QA directory; preserve previous evidence')
    inputs = [args.candidate.resolve(), args.baseline_image_dir.resolve(), args.published_dir.resolve()]
    if any(out == path or out in path.parents or path in out.parents for path in inputs):
        raise ValueError('Qualification output must be separate from all input directories')
    for version in (args.baseline_version, args.candidate_version):
        if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
            raise ValueError('Expected an explicit three-part version')
    sequences = [args.baseline_sequence, *(item[2] for item in args.release), args.candidate_sequence]
    if any(type(value) is not int or not 1 <= value < 2 ** 63 for value in sequences):
        raise ValueError('Sequence must be positive')
    if sequences != sorted(set(sequences)):
        raise ValueError('Signed sequence must increase at every update hop')
    if len({item[0] for item in args.release}) != len(args.release):
        raise ValueError('Duplicate release tag')
    checksum = installer_digest(args.baseline_image_dir)
    bundle = args.candidate / 'ToddlerBox-update.pyz'
    with zipfile.ZipFile(bundle) as archive:
        if archive.getinfo('manifest.json').file_size > 16384:
            raise ValueError('Oversized candidate manifest')
        manifest = json.loads(archive.read('manifest.json'))
    if not manifest.get('app') or not re.fullmatch(r'[0-9a-f]{16}', manifest['source']['content']):
        raise ValueError('Qualification requires a combined app/system candidate')
    revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if manifest['source']['git'] != revision:
        raise ValueError('Candidate must have been built from this exact checkout revision')
    if manifest['source']['content'] != checkout_source(root):
        raise ValueError('Candidate content differs from the checkout under qualification')
    return out, checksum, manifest


def prepare_share(args, out, manifest):
    """Ephemeral test signing key stays in memory; only public bytes reach disk."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    share = out / 'share'
    share.mkdir()
    shutil.copyfile(ROOT / 'scripts/update-vm-guest.py', share / 'guest.py')
    for tag, _, _ in args.release:
        target = share / tag
        target.mkdir()
        for name in ('stable.json', 'stable.json.sig', 'ToddlerBox-update.pyz'):
            shutil.copyfile(args.published_dir / tag / name, target / name)
    target = share / 'candidate'
    target.mkdir()
    bundle = target / 'ToddlerBox-update.pyz'
    shutil.copyfile(args.candidate / bundle.name, bundle)
    value = {'format': 1, 'channel': 'stable', 'sequence': args.candidate_sequence,
             'tag': 'vm-dev-' + manifest['source']['content'], 'source': manifest['source']['content'],
             'platform': 'ubuntu24.04-x86_64', 'schema': {'version': 1, 'typing': 1, 'paint': 1},
             'asset': bundle.name, 'bytes': bundle.stat().st_size, 'sha256': sha(bundle)}
    data = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    key = Ed25519PrivateKey.generate()
    (target / 'stable.json').write_bytes(data)
    (target / 'stable.json.sig').write_bytes(key.sign(data))
    (share / 'vm-public-key.pem').write_bytes(key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    return share, value


class UpdateChain:
    def __init__(self, args, module):
        self.args, self.module = args, module
        self.out, checksum, self.manifest = validate_inputs(args)
        # No output, provisioning or writable disk access before validation.
        self.out.mkdir()
        self.share, self.candidate = prepare_share(args, self.out, self.manifest)
        self.qa = module.Qualification(args.baseline_image_dir, self.out / 'vm')
        self.qa.name = 'toddlerbox-update-chain-qa'
        self.qa.share = self.share
        self.report = {'status': 'running', 'checks': [], 'inputs': {
            'installer_version': args.baseline_version, 'installer_sha256': checksum,
            'signed_hops': args.release, 'candidate_git': self.manifest['source']['git'],
            'candidate_source': self.candidate['source'], 'candidate_sha256': self.candidate['sha256'],
            'candidate_version': args.candidate_version, 'vm_sequence': args.candidate_sequence},
            'platform': 'Ubuntu 24.04 x86-64 Q35/UEFI/TCG, 2 CPUs, 4 GiB, no NIC, disposable overlay',
            'limits': ['Synthetic VM signing identity; no production signing key used',
                       'Class C remains from the published installer',
                       'No physical HP input, Wi-Fi or acoustic validation',
                       'No fresh qualification of unchanged Music PCM; separate fresh-install job covers it']}
        self.save()

    def save(self):
        (self.out / 'results.json').write_text(json.dumps(self.report, indent=2) + '\n')

    def passed(self, text):
        self.report['checks'].append(text)
        self.save()
        print('QA: ' + text, flush=True)

    def serial(self, script, timeout=240):
        return self.qa.serial(script, timeout=timeout)

    def mount(self):
        self.serial('mkdir -p /qa; mountpoint -q /qa || mount -t 9p -o trans=virtio,version=9p2000.L,ro qa /qa')

    def guest(self, action, *arguments, app=False, background=False):
        python = '/opt/toddlerbox/current/.venv/bin/python' if app else 'python3'
        command = shlex.join([python, '-B', '/qa/guest.py', action, *map(str, arguments)])
        if background:
            command = ('rm -f /root/update-qa/boundary.json; nohup ' + command +
                       ' >/root/update-qa/operation.log 2>&1 </dev/null &')
        return self.serial(command, timeout=900)

    def version(self, version, source=None, status=None):
        arguments = ['--version', version]
        if source: arguments += ['--source', source]
        if status: arguments += ['--status', status]
        self.guest('version', *arguments, app=True)

    def observe(self, label, accept=True, setup=False):
        self.serial('toddlerbox-maintenance --action test')
        self.qa.wait_text('Paint', 'Math', 'Reading')
        self.qa.wait_health()
        predicate = ("Path('/run/toddlerbox-system/setup-test-observed').exists()" if setup else
                     "__import__('boot_recovery').latest(Path('/'))[1]['observed']")
        self.serial("export PYTHONPATH=/usr/local/lib/toddlerbox-system\n"
                    "for i in $(seq 1 90); do\n"
                    f"if python3 -B -c {shlex.quote('from pathlib import Path; assert ' + predicate)}; then exit 0; fi\n"
                    "sleep 1\ndone\nexit 1")
        self.qa.shot('checkpoint-' + label)
        self.qa.key('ctrl-alt-home', 2500)
        self.qa.mode('parent')
        self.qa.wait_text('Parent')
        if accept:
            self.serial('toddlerbox-maintenance --action accept')

    def preserve_baseline(self):
        self.serial("sync; nohup sh -c 'sleep 2; poweroff' >/dev/null 2>&1 </dev/null &")
        self.qa.docker('wait', self.qa.name, timeout=120, stdout=subprocess.DEVNULL)
        self.qa.stop()
        disk = self.qa.out / 'target.qcow2'
        disk.rename(self.qa.out / 'published-baseline.qcow2')
        self.qa.docker('run', '--rm', '--network=none', '--user', f'{os.getuid()}:{os.getgid()}',
                       '-v', f'{self.qa.out}:/vm', 'toddlerbox-image-tools',
                       'qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b',
                       '/vm/published-baseline.qcow2', '/vm/target.qcow2')
        self.qa.start()
        self.qa.mode('parent')
        self.mount()
        self.passed('Preserved published baseline; all candidate writes use a disposable overlay')

    def install_candidate(self, boundary=None, background=False):
        args = ['--directory', '/qa/candidate', '--sequence', str(self.args.candidate_sequence)]
        if boundary: args += ['--boundary', boundary]
        self.guest('install', *args, background=background)

    def rollback(self, baseline):
        self.guest('rollback')
        self.qa.mode('parent')
        self.version(*baseline, status='rolled-back')
        self.guest('check-pair')

    def reset(self):
        before = self.serial('cat /proc/sys/kernel/random/boot_id')
        # Extract only the boot UUID for the live comparison; never publish it.
        boot = re.search(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', before)[0]
        self.module.command('system_reset')
        time.sleep(10)
        self.serial(f'test "$(cat /proc/sys/kernel/random/boot_id)" != {shlex.quote(boot)}')
        self.mount()

    def interrupt(self, boundary, baseline):
        if boundary == 'restoring':
            self.install_candidate()
            self.guest('rollback', '--boundary', boundary, background=True)
        else:
            self.install_candidate(boundary, background=True)
        self.serial('for i in $(seq 1 600); do test ! -f /root/update-qa/boundary.json || exit 0; sleep 1; done; '
                    'tail -60 /root/update-qa/operation.log; exit 1', timeout=660)
        print(self.guest('boundary', '--boundary', boundary, '--source', self.candidate['source']), flush=True)
        self.reset()
        self.qa.mode('parent')
        if boundary == 'pending':
            self.version(self.args.candidate_version, self.candidate['source'], 'pending')
            self.rollback(baseline)
        else:
            self.version(*baseline, status='rolled-back')
            self.guest('check-pair')
        self.passed(f'QMP reset after durable {boundary}: resident recovery and exact known-good pair/data checks')

    def run(self):
        try:
            self.qa.install()
            self.mount()
            self.guest('seed')
            self.version(self.args.baseline_version)
            self.serial("export PYTHONPATH=/usr/local/lib/toddlerbox-system\n"
                        "python3 -B -c 'import json; from pathlib import Path; "
                        f"assert json.loads(Path(\"/var/lib/toddlerbox-system/release-sequence.json\").read_text())[\"sequence\"]=={self.args.baseline_sequence}'")
            self.observe('installer-baseline', accept=False, setup=True)
            self.serial('toddlerbox-maintenance --action check network skipped\n'
                        'toddlerbox-maintenance --action check audio skipped\n'
                        'toddlerbox-maintenance --action check input skipped\n'
                        'toddlerbox-maintenance --action check recovery passed\n'
                        'toddlerbox-maintenance --action check drive skipped\n'
                        'toddlerbox-maintenance --action finish')
            self.passed('Verified published installer, authenticated setup and genuine supervised child/escape')
            baseline = (self.args.baseline_version, None)
            for tag, version, sequence in self.args.release:
                self.guest('install', '--directory', '/qa/' + tag, '--sequence', sequence)
                self.version(version, status='pending')
                self.observe(tag)
                value = json.loads((self.share / tag / 'stable.json').read_text())
                self.version(version, value['source'], 'accepted')
                baseline = (version, value['source'])
                self.passed(f'Shipped-key verified {tag}, sequence {sequence}, installed and supervised acceptance')
            self.preserve_baseline()
            self.guest('untrusted', '--directory', '/qa/candidate', '--sequence', self.args.candidate_sequence)
            self.guest('inject-key')
            self.guest('save-pair')
            self.install_candidate()
            self.version(self.args.candidate_version, self.candidate['source'], 'pending')
            self.observe('dev-signed')
            self.version(self.args.candidate_version, self.candidate['source'], 'accepted')
            self.passed('Exact dev bundle installed by the baseline updater after VM-only signature verification and supervised acceptance')
            bundle = '/qa/candidate/ToddlerBox-update.pyz'
            digest = self.candidate['sha256']
            self.serial(f'if output=$(toddlerbox-update {bundle} {digest} 2>&1); then exit 1; fi\n'
                        'case "$output" in *--unsigned-recovery*) ;; *) exit 1 ;; esac')
            self.rollback(baseline)
            # Recovery bootstrap explicitly executes the checksum-verified dev
            # zip: the historical baseline command predates this CLI flag.
            self.serial(f'python3 {bundle} --sha256 {digest} --unsigned-recovery', timeout=900)
            self.version(self.args.candidate_version, self.candidate['source'], 'pending')
            self.observe('dev-unsigned-recovery')
            self.rollback(baseline)
            self.passed('Unsigned refusal, explicit checksum-verified recovery bootstrap, supervised acceptance and exact rollback')
            for boundary in ('applying', 'system-replaced', 'pending', 'restoring'):
                self.interrupt(boundary, baseline)
            self.install_candidate()
            self.observe('final-accepted')
            self.serial('toddlerbox-mode child')
            self.qa.wait_health()
            self.reset()
            self.qa.wait_text('Paint', 'Math', 'Reading')
            self.qa.wait_health()
            self.version(self.args.candidate_version, self.candidate['source'], 'accepted')
            self.qa.shot('checkpoint-accepted-reboot')
            self.passed('Final exact candidate accepted reboot, healthy child frames and unchanged synthetic work/config/resident code')
            self.report['status'] = 'passed'
            print('UPDATE_CHAIN_VM_PASS', flush=True)
        except Exception as error:
            self.report.update(status='failed', error=type(error).__name__)
            raise
        finally:
            self.save()
            self.qa.stop()
            # No raw serial output, VM disk, password-entry probe or key is an
            # evidence artifact. Selected checkpoint screenshots are allowlisted.
            for name in ('probe.png', 'probe.ppm', 'ocr-probe.png'):
                (self.qa.out / name).unlink(missing_ok=True)
            for path in self.qa.out.glob('checkpoint-*.png'):
                shutil.copyfile(path, self.out / path.name)


def main(module=None):
    args = parse_args()
    socket.setdefaulttimeout(20)
    if module is None:
        spec = importlib.util.spec_from_file_location('release_qa', ROOT / 'scripts/qualify-release-vm.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    UpdateChain(args, module).run()


if __name__ == '__main__': main()
