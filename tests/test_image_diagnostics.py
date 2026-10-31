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
