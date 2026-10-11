"""The image and existing-install patch must deploy the same DNS ownership."""
import configparser
from pathlib import Path
import subprocess

ROOT = Path(__file__).parents[1]


def test_image_and_parent_patch_install_identical_direct_dns_policy(tmp_path):
    policy = ROOT / 'system/90-toddlerbox-dns.conf'
    source = (ROOT / 'system/configure-rootfs.sh').read_text()
    line = next(line for line in source.splitlines() if '90-toddlerbox-dns.conf' in line)
    # Execute the actual image installation line, with only its destination sandboxed.
    target = tmp_path / 'conf.d'
    target.mkdir()
    line = line.replace('/etc/NetworkManager/conf.d/', str(target) + '/')
    subprocess.run(['bash', '-c', line], env={'source_dir':str(ROOT/'system')}, check=True)
    deployed = target / policy.name
    assert deployed.read_bytes() == policy.read_bytes()
    config = configparser.ConfigParser()
    config.read(deployed)
    assert dict(config['main']) == {'dns':'default', 'rc-manager':'file'}
    assert deployed.stat().st_mode & 0o777 == 0o644
    patch = (ROOT/'scripts/install-drive-setup-patch.sh').read_text()
    assert "'system/90-toddlerbox-dns.conf': ('etc/NetworkManager/conf.d/90-toddlerbox-dns.conf', 0o644)" in patch
    # The target is owned by NetworkManager, not a nonexistent local stub.
    image = (ROOT/'system/make-images.sh').read_text()
    assert 'ln -s /run/NetworkManager/resolv.conf rootfs/etc/resolv.conf' in image
