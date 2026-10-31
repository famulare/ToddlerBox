"""Image-only diagnostic availability and automatic-start policy."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).parents[1]


def test_image_diagnostics_preserve_audio_and_add_requested_tools():
    packages = (ROOT / 'system/packages.txt').read_text().splitlines()
    assert set(('libinput-tools', 'evtest', 'smartmontools', 'pciutils',
                'alsa-utils', 'pulseaudio-utils', 'pipewire')) <= set(packages)
    for recipe in ('Dockerfile.base', 'Dockerfile.compact'):
        assert 'packages.txt' in (ROOT / 'system' / recipe).read_text()


def test_image_disables_package_default_smart_startup():
    recipe = (ROOT / 'system/configure-rootfs.sh').read_text()
    assert 'update-rc.d smartmontools disable' in recipe
    assert 'systemctl disable smartmontools.service smartd.service' in recipe
    assert 'systemctl mask smartmontools.service smartd.service' in recipe
    assert recipe.index('systemctl mask smartmontools.service') < recipe.index("printf '%s\\n' \"$release_id\"")


def test_diagnostic_qualification_script_is_valid_shell():
    subprocess.run(['bash', '-n', str(ROOT / 'system/check-diagnostic-tools.sh')], check=True)


def test_smart_masks_override_package_enablement_in_disposable_root(tmp_path):
    import shutil
    import pytest

    systemctl = shutil.which('systemctl')
    if systemctl is None:
        pytest.skip('Linux systemctl required for offline image policy check')
    units = tmp_path / 'usr/lib/systemd/system'
    units.mkdir(parents=True)
    (units / 'smartmontools.service').write_text(
        '[Unit]\nDescription=synthetic SMART daemon\n[Service]\nExecStart=/bin/true\n'
        '[Install]\nWantedBy=multi-user.target\nAlias=smartd.service\n')
    (units / 'smartd.service').symlink_to('smartmontools.service')
    def control(*args):
        return subprocess.run([systemctl, '--root', str(tmp_path), *args],
                              check=True, capture_output=True, text=True)
    control('enable', 'smartmontools.service')
    # Execute the actual recipe policy against package-like default enablement.
    recipe = (ROOT / 'system/configure-rootfs.sh').read_text().splitlines()
    for line in recipe:
        if line.startswith(('systemctl disable smartmontools', 'systemctl mask smartmontools')):
            control(*line.split()[1:])
    for name in ('smartmontools.service', 'smartd.service'):
        result = subprocess.run([systemctl, '--root', str(tmp_path), 'is-enabled', name],
                                capture_output=True, text=True)
        assert result.stdout.strip() == 'masked'
        assert (tmp_path / 'etc/systemd/system' / name).readlink() == Path('/dev/null')
    assert not list((tmp_path / 'etc/systemd/system/multi-user.target.wants').glob('*smart*'))


def test_diagnostic_smoke_check_is_image_only_and_parent_guarded():
    recipe = (ROOT / 'system/configure-rootfs.sh').read_text()
    assert 'check-diagnostic-tools.sh" /usr/local/sbin/toddlerbox-check-diagnostics' in recipe
    script = (ROOT / 'system/check-diagnostic-tools.sh').read_text()
    assert '$EUID == 0' in script and '/run/toddlerbox-system/mode' in script
    assert 'libinput record --help' in script
    assert 'systemctl show "$unit" --property=ActiveState --value' in script
    qualification = (ROOT / 'scripts/qualify-release-vm.py').read_text()
    assert '/usr/local/sbin/toddlerbox-check-diagnostics' in qualification
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location('diagnostic_update_payload', ROOT / 'system/update_bundle.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    assert 'toddlerbox-check-diagnostics' not in module.FILES


def test_new_image_inventory_checks_reject_monitoring_and_command_failure(monkeypatch):
    import importlib.util
    from types import SimpleNamespace
    import pytest
    spec = importlib.util.spec_from_file_location('image_inventory_qa', ROOT / 'scripts/qualify-image-diagnostics.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    read_text = Path.read_text
    monkeypatch.setattr(Path, 'read_text', lambda p, *a, **k: 'parent' if str(p) == '/run/toddlerbox-system/mode' else read_text(p, *a, **k))
    fault = [None]
    def bounded(argv):
        if argv[:2] == ['dpkg-query', '-W']:
            return 'baseline\t1\nsmartmontools\t1\nlibinput-tools\t1\nevtest\t1\npciutils\t1\n'
        if argv[:2] == ['dpkg-query', '-L']:
            if argv[-1] == 'smartmontools':
                return '/usr/lib/systemd/system/smartmontools.service\n/usr/lib/systemd/system/smartd.service\n' + ('/etc/cron.daily/monitor\n' if fault[0] == 'cron' else '')
            return '/usr/bin/diagnostic\n'
        if argv[:2] == ['systemctl', 'show']:
            return 'active' if fault[0] == 'active' else 'inactive'
        if argv == ['libinput', 'list-devices'] and fault[0] == 'enumeration':
            raise subprocess.TimeoutExpired(argv, 8)
        return ''
    monkeypatch.setattr(module, 'bounded', bounded)
    monkeypatch.setattr(module.subprocess, 'run', lambda *_a, **_k: SimpleNamespace(stdout='enabled' if fault[0] == 'enabled' else 'masked'))
    module.check({'baseline'})
    for case in ('cron', 'active', 'enabled'):
        fault[0] = case
        with pytest.raises(AssertionError):
            module.check({'baseline'})
    fault[0] = 'enumeration'
    with pytest.raises(subprocess.TimeoutExpired):
        module.check({'baseline'})


def test_diagnostic_baseline_inventory_has_recorded_provenance():
    import hashlib
    baseline = ROOT / 'docs/dev/evidence/diagnostic-baseline-packages.tsv'
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == '36c1e45b42c042e832471b68795094af6d26be388bac4f4215cba6873ec19a85'
    names = {line.split('\t')[0] for line in baseline.read_text().splitlines()}
    assert not names.intersection({'libinput-tools', 'evtest', 'smartmontools', 'pciutils'})


def test_vm_diagnostic_command_is_valid_shell_and_python(tmp_path):
    import ast
    import importlib.util
    import json
    import pytest
    spec = importlib.util.spec_from_file_location('diagnostic_serial_qa', ROOT / 'scripts/qualify-release-vm.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    qa = module.Qualification.__new__(module.Qualification)
    qa.out = tmp_path
    calls = []
    class StopAfterDiagnostic(Exception):
        pass
    def serial(script, **kwargs):
        calls.append(script)
        if len(calls) > 1:
            raise StopAfterDiagnostic()
        subprocess.run(['bash', '-n'], input=script, text=True, check=True)
        python = script.split("python3 - <<'DIAGNOSTIC_PY'\n", 1)[1].rsplit('\nDIAGNOSTIC_PY', 1)[0]
        parsed = ast.parse(python)
        names = ast.literal_eval(parsed.body[-1].value.args[0])
        assert 'libinput-bin' in names and all('\t' not in n for n in names)
        return 'TBX_DIAGNOSTICS:' + json.dumps({'checks': ['synthetic marker']}) + '\r\n'
    qa.serial = serial
    with pytest.raises(StopAfterDiagnostic):
        qa.smoke()
    assert json.loads((tmp_path / 'diagnostics.json').read_text()) == {'checks': ['synthetic marker']}
