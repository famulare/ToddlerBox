"""Ubuntu update-only qualification on a disposable synthetic appliance overlay.

uv run --frozen python scripts/qualify-audio-update.py CANDIDATE_DIR NEW_QA_DIR
Requires the preserved qualified 0.3 base and published 0.4 update in build/.
No physical disks, family packages or real provider credentials are used.
Provisioning changes only the disposable VM's synthetic parent password.
Raw serial logs stay private; publish selected screenshots and results only.
"""
import base64
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_qa', ROOT / 'scripts/qualify-release-vm.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def main():
    candidate, out = (Path(p).resolve() for p in sys.argv[1:])
    if out.exists():
        raise ValueError('Use a new QA directory; preserve old evidence')
    out.mkdir(parents=True)
    qa = module.Qualification.__new__(module.Qualification)
    qa.out, qa.name = out, 'toddlerbox-audio-update-qa'
    qa.password, qa.authenticated = secrets.token_hex(10), False
    os.environ['TODDLERBOX_VM_DIR'] = str(out)
    boot = ROOT / 'build/audio-polish/usb-vm'
    qa.docker('run', '--rm', '--network=none', '-v', f'{ROOT}/build/appliance-qualified:/base:ro',
              '-v', f'{out}:/vm', 'toddlerbox-image-tools', 'bash', '-ec',
              f'qemu-img create -f qcow2 -F qcow2 -b /base/disk.qcow2 /vm/target.qcow2; chown {os.getuid()}:{os.getgid()} /vm/target.qcow2')

    def start(provision=False):
        qa.docker('run', '-d', '--name', qa.name, '--user', f'{os.getuid()}:{os.getgid()}',
                  '--network=none', '-v', f'{ROOT}/build/appliance-qualified:/base:ro',
                  '-v', f'{out}:/vm', '-v', f'{boot}:/boot:ro', '-v', f'{candidate}:/qa:ro',
                  '-v', f'{ROOT}/build/music-expansion-qa/release:/prior:ro',
                  'toddlerbox-image-tools', 'qemu-system-x86_64', '-accel', 'tcg,thread=multi',
                  '-machine', 'q35', '-cpu', 'qemu64', '-smp', '2', '-m', '2048',
                  '-kernel', '/boot/vmlinuz', '-initrd', '/boot/initrd', '-append',
                  'root=/dev/vda2 rw console=tty0 console=ttyS0,115200' + (' init=/bin/bash' if provision else ''),
                  '-drive', 'if=virtio,format=qcow2,file=/vm/target.qcow2',
                  '-fsdev', 'local,id=qa,path=/qa,security_model=none,readonly=on',
                  '-device', 'virtio-9p-pci,fsdev=qa,mount_tag=qa',
                  '-fsdev', 'local,id=prior,path=/prior,security_model=none,readonly=on',
                  '-device', 'virtio-9p-pci,fsdev=prior,mount_tag=prior',
                  '-device', 'virtio-vga', '-device', 'qemu-xhci', '-device', 'usb-tablet', '-nic', 'none',
                  '-audiodev', 'wav,id=audio,path=/vm/audio.wav', '-device', 'ich9-intel-hda',
                  '-device', 'hda-duplex,audiodev=audio', '-display', 'none',
                  '-qmp', 'unix:/vm/qmp.sock,server=on,wait=off',
                  '-chardev', 'socket,id=serial,path=/vm/serial.sock,server=on,wait=off,logfile=/vm/serial.log',
                  '-serial', 'chardev:serial', stdout=subprocess.DEVNULL)
        for attempt in range(60):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                try:
                    probe.connect(str(out/'serial.sock'))
                    return
                except (FileNotFoundError, ConnectionRefusedError):
                    time.sleep(.5)
        raise TimeoutError('QEMU serial socket did not become ready')

    def install(where, sequence):
        print(qa.serial(f'''
export PYTHONPATH=/usr/local/lib/toddlerbox-system
mkdir -p /qa /prior
mountpoint -q /qa || mount -t 9p -o trans=virtio,version=9p2000.L,ro qa /qa
mountpoint -q /prior || mount -t 9p -o trans=virtio,version=9p2000.L,ro prior /prior
python3 - <<'INNER'
from pathlib import Path
from release_client import verify
from update_bundle import run, sha
p=Path('{where}')
v=verify((p/'stable.json').read_bytes(), (p/'stable.json.sig').read_bytes(), Path('/etc/toddlerbox/release-public-key.pem').read_bytes())
assert v['sequence']=={sequence}
b=p/'ToddlerBox-update.pyz'; assert sha(b)==v['sha256']
print(run(b,v['sha256'],release_sequence=v['sequence'],release_source=v['source']))
INNER
sha256sum -c /root/appliance-qa/creations.sha256
sha256sum -c /root/qa-config.sha256
''', timeout=400), flush=True)

    def observe_accept(label):
        qa.serial('toddlerbox-maintenance --action test')
        qa.wait_health()
        qa.serial('''
export PYTHONPATH=/usr/local/lib/toddlerbox-system
for i in $(seq 1 60); do
 if python3 -c 'from pathlib import Path;from boot_recovery import latest;assert latest(Path("/"))[1]["observed"]' 2>/dev/null; then exit 0; fi
 sleep 1
done
exit 1
''')
        qa.shot(label)
        qa.key('ctrl-alt-home', 2500)
        qa.mode('parent')
        qa.serial('toddlerbox-maintenance --action accept')

    try:
        start(provision=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(.5)
            for attempt in range(60):
                try:
                    conn.connect(str(out/'serial.sock'))
                    break
                except FileNotFoundError:
                    time.sleep(.5)
            conn.sendall(b'\r')
            qa.until(conn, rb'root@.*#', 180)
            # This synthetic password is never printed or included in public evidence.
            script = f"mount -o remount,rw /; printf 'parent:{qa.password}\\n' | chpasswd; sync; echo PROVISIONED\n"
            encoded = base64.b64encode(script.encode()).decode()
            conn.sendall(f'printf %s {encoded} | base64 -d | bash\n'.encode())
            qa.until(conn, rb'\r?\nPROVISIONED\r?\n', 60)
        qa.stop()
        start()
        qa.serial('sha256sum /etc/toddlerbox/config.yaml >/root/qa-config.sha256; toddlerbox-mode parent')
        qa.mode('parent')
        print('QA: installed signed 0.4 baseline next', flush=True)
        install('/prior', 2)
        observe_accept('baseline-0.4')
        print('QA: apply USB/DNS source patch; install signed 0.5', flush=True)
        qa.serial('sh /qa/checkout/scripts/install-drive-setup-patch.sh')
        install('/qa', 3)
        observe_accept('candidate-0.5')
        print(qa.serial('''
/opt/toddlerbox/current/.venv/bin/python - <<'INNER'
import importlib.metadata
from pathlib import Path
from toddlerbox.music.library import load_library
from unittest.mock import Mock
assert importlib.metadata.version('ToddlerBox')=='0.5.0'
assert len(load_library(Path('/opt/toddlerbox/current/assets/music'),Mock())[0])==18
INNER
toddlerbox-maintenance --action audio-defaults
sha256sum /etc/toddlerbox/config.yaml >/root/qa-config.sha256
toddlerbox-mode child
'''), flush=True)
        qa.wait_health()
        print(qa.serial('''
uid=$(id -u toddlerbox)
runuser -u toddlerbox -- env XDG_RUNTIME_DIR=/run/user/$uid wpctl get-volume @DEFAULT_AUDIO_SINK@ >/root/qa-volume.txt
cat /root/qa-volume.txt
python3 - <<'INNER'
from pathlib import Path
value=Path('/root/qa-volume.txt').read_text().strip()
assert value.startswith('Volume: ') and '[MUTED]' not in value, value
assert abs(float(value.split()[1])-.80)<.015, value
INNER
test "$(cat /run/toddlerbox-system/mode)" = child
sha256sum -c /root/appliance-qa/creations.sha256
'''), flush=True)
        from PIL import Image
        w, h = Image.open(qa.shot('louder-launcher')).size
        icon=max(120,min(184,int(min(w,h)*.23))); gap=int(icon*.3)
        left=w//2-(3*icon+2*gap)//2; top=h//2-(2*icon+gap)//2
        qa.click(left+2*(icon+gap)+icon//2,top+icon//2)
        time.sleep(4)
        qa.wait_audio()
        qa.shot('music-0.5')
        qa.key('ctrl-alt-home', 2500)
        qa.mode('parent')
        print('QA: explicit rollback', flush=True)
        print(qa.serial('toddlerbox-maintenance --action rollback'), flush=True)
        print(qa.serial('''
/opt/toddlerbox/current/.venv/bin/python -c "import importlib.metadata; assert importlib.metadata.version('ToddlerBox')=='0.4.0'"
sha256sum -c /root/appliance-qa/creations.sha256
test -f /usr/local/lib/toddlerbox-system/tbx_sync/usb_setup.py
grep '^dns=default' /etc/NetworkManager/conf.d/90-toddlerbox-dns.conf
'''), flush=True)
        install('/qa', 3)
        # Explicit opt-in changed config, so pin its new durable bytes for repeat checks.
        observe_accept('reinstalled-0.5')
        qa.serial('toddlerbox-mode child')
        qa.wait_health()
        module.command('system_reset')
        time.sleep(10)
        qa.wait_health()
        qa.shot('rebooted-0.5')
        qa.serial('sha256sum -c /root/appliance-qa/creations.sha256')
        (out/'results.json').write_text(json.dumps({'platform':'Ubuntu24.04 x86-64 Q35 TCG, 2CPU 2GiB, no NIC, virtual HDA; direct-kernel boot of disposable qualified0.3 overlay', 'checks':['installed signed0.4 baseline and accepted genuine supervised child frames', 'source USB/DNS patch, signed0.5 install and acceptance', 'config bytes preserved by installer; explicit louder opt-in', 'native wpctl startup volume and actual HDA Music PCM', 'independent Ctrl+Alt+Home escape', 'explicit rollback to0.4 and signed0.5 reinstall', 'accepted0.5 reboot health and synthetic Paint/Typing exact SHA preservation'], 'limits':['no new ISO/fresh installation or physical HP speaker calibration', 'USB/DNS remain separate trusted source patch; existing signed allowlist unchanged']}, indent=2)+'\n')
        print('AUDIO_UPDATE_VM_PASS', flush=True)
    finally:
        qa.stop()


if __name__ == '__main__':
    main()
