"""Ubuntu 0.5.1 update qualification on a disposable synthetic appliance overlay.

uv run --frozen python scripts/qualify-patch-update.py CANDIDATE_DIR NEW_QA_DIR
Requires the preserved qualified 0.5.0 overlay and its qualified 0.3 backing disk.
No physical disks, family packages or real provider credentials are used.
Provisioning changes only the disposable VM's synthetic parent password.
Raw serial logs stay private; publish selected screenshots and results only.
"""
import base64
from array import array
import math
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import textwrap

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_qa', ROOT / 'scripts/qualify-release-vm.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def main():
    candidate, out = (Path(p).resolve() for p in sys.argv[1:3])
    resume = sys.argv[3:] in (["--resume"], ["--resume-recovery"])
    recovery_only = sys.argv[3:] == ["--resume-recovery"]
    if sys.argv[3:] and not resume:
        raise ValueError("Only --resume or --resume-recovery is accepted after candidate/output")
    # Validate before provisioning or opening any disk writable. Qualified
    # bases are never legitimate outputs, including through symlink aliases.
    if out.parent != (ROOT / 'build').resolve() or not out.name.startswith('responsive-update-vm-'):
        raise ValueError('Output must be a disposable build/responsive-update-vm-* directory')
    if out.exists() and not resume:
        raise ValueError('Use a new QA directory; preserve old evidence')
    if recovery_only and not (out/'results.json').is_file():
        raise ValueError('Recovery-only continuation requires prior completed checks')
    out.mkdir(parents=True, exist_ok=resume)
    qa = module.Qualification.__new__(module.Qualification)
    qa.out, qa.name = out, 'toddlerbox-patch-update-qa'
    qa.password, qa.authenticated = secrets.token_hex(10), False

    def diagnostic(script, timeout=180):
        return qa.serial(textwrap.dedent(script), timeout=timeout)

    os.environ['TODDLERBOX_VM_DIR'] = str(out)
    boot = ROOT / 'build/audio-polish/usb-vm'
    if not resume:
        qa.docker('run', '--rm', '--network=none', '-v', f'{ROOT}/build/appliance-qualified:/base:ro',
              '-v', f'{ROOT}/build/audio-polish/final2-vm:/known:ro',
              '-v', f'{out}:/vm', 'toddlerbox-image-tools', 'bash', '-ec',
              f'qemu-img create -f qcow2 -F qcow2 -b /known/target.qcow2 /vm/target.qcow2; chown {os.getuid()}:{os.getgid()} /vm/target.qcow2')

    def start(provision=False):
        qa.docker('run', '-d', '--name', qa.name, '--user', f'{os.getuid()}:{os.getgid()}',
                  '--network=none', '-v', f'{ROOT}/build/appliance-qualified:/base:ro',
                  '-v', f'{out}:/vm', '-v', f'{boot}:/boot:ro', '-v', f'{candidate}:/qa:ro',
                  '-v', f'{ROOT}/build/audio-polish/final2-vm:/known:ro',
                  'toddlerbox-image-tools', 'qemu-system-x86_64', '-accel', 'tcg,thread=multi',
                  '-machine', 'q35', '-cpu', 'qemu64', '-smp', '2', '-m', '2048',
                  '-kernel', '/boot/vmlinuz', '-initrd', '/boot/initrd', '-append',
                  'root=/dev/vda2 rw console=tty0 console=ttyS0,115200' + (' init=/bin/bash' if provision else ''),
                  '-drive', 'if=virtio,format=qcow2,file=/vm/target.qcow2',
                  '-fsdev', 'local,id=qa,path=/qa,security_model=none,readonly=on',
                  '-device', 'virtio-9p-pci,fsdev=qa,mount_tag=qa',
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
        print(diagnostic(f'''
export PYTHONPATH=/usr/local/lib/toddlerbox-system
mkdir -p /qa /prior
mountpoint -q /qa || mount -t 9p -o trans=virtio,version=9p2000.L,ro qa /qa
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
        diagnostic('toddlerbox-maintenance --action test')
        qa.wait_health()
        diagnostic('''
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
        diagnostic('toddlerbox-maintenance --action accept')

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
        if resume:
            print('QA: resume exact accepted checkpoint after harness-only correction', flush=True)
            diagnostic("""
mkdir -p /qa
mountpoint -q /qa || mount -t 9p -o trans=virtio,version=9p2000.L,ro qa /qa
PYTHONPATH=/usr/local/lib/toddlerbox-system python3 -B - <<'INNER'
from pathlib import Path
from release_client import verify
from update_bundle import sha
from boot_recovery import latest
v=verify(Path('/qa/stable.json').read_bytes(),Path('/qa/stable.json.sig').read_bytes(),Path('/etc/toddlerbox/release-public-key.pem').read_bytes())
assert sha(Path('/qa/ToddlerBox-update.pyz'))==v['sha256']
state=latest(Path('/'))[1]
assert state['status']=='accepted' and state['bundle']==v['sha256']
assert state['source']['content']==v['source'] and Path('/opt/toddlerbox/current').resolve().name==v['source']
INNER
sha256sum -c /root/appliance-qa/creations.sha256
sha256sum -c /root/qa-config.sha256
toddlerbox-mode parent
""")
            qa.mode('parent')
        else:
            diagnostic('sha256sum /etc/toddlerbox/config.yaml >/root/qa-config.sha256; toddlerbox-mode parent')
            qa.mode('parent')
            diagnostic("/opt/toddlerbox/current/.venv/bin/python -B -c \"import importlib.metadata; assert importlib.metadata.version('ToddlerBox')=='0.5.0'\"")
            print('QA: qualified 0.5 baseline; install signed 0.5.1', flush=True)
            install('/qa', 4)
            observe_accept('candidate-0.5.1')
        if recovery_only:
            diagnostic('toddlerbox-mode child')
            qa.wait_health()
        else:
            print(diagnostic("cat /qa/native-checks.py >/tmp/tbx-native-checks.py; chmod 0444 /tmp/tbx-native-checks.py; /opt/toddlerbox/current/.venv/bin/python -B /tmp/tbx-native-checks.py", timeout=180), flush=True)
            print(diagnostic('''
    /opt/toddlerbox/current/.venv/bin/python -B - <<'INNER'
    import importlib.metadata
    from pathlib import Path
    from toddlerbox.music.library import load_library
    from unittest.mock import Mock
    assert importlib.metadata.version('ToddlerBox')=='0.5.1'
    assert len(load_library(Path('/opt/toddlerbox/current/assets/music'),Mock())[0])==18
    INNER
    PYTHONPATH=/usr/local/lib/toddlerbox-system python3 -B - <<'INNER'
    from pathlib import Path
    import json, runpy
    record=runpy.run_path('/usr/local/sbin/toddlerbox-install-release')['tree_record']
    Path('/root/qa-app-tree.json').write_text(json.dumps(record(Path('/opt/toddlerbox/current').resolve(),production=True),sort_keys=True))
    INNER
    toddlerbox-maintenance --action status
    PYTHONPATH=/usr/local/lib/toddlerbox-system python3 -B - <<'INNER'
    from pathlib import Path
    import json, runpy
    record=runpy.run_path('/usr/local/sbin/toddlerbox-install-release')['tree_record']
    assert json.dumps(record(Path('/opt/toddlerbox/current').resolve(),production=True),sort_keys=True)==Path('/root/qa-app-tree.json').read_text()
    print('Parent status preserved immutable release tree: PASS')
    INNER
    sha256sum /etc/toddlerbox/config.yaml >/root/qa-config.sha256
    toddlerbox-mode child
    '''), flush=True)
            qa.wait_health()
            print(diagnostic('''
    uid=$(id -u toddlerbox)
    # Under TCG both actual0.5.0/0.5.1 Python initializers can hit the unchanged
    # outer2s deadline before import completes. Record the fallback; make the
    # parent volume setting explicit for HDA PCM checks, not a startup claim.
    runuser -u toddlerbox -- env XDG_RUNTIME_DIR=/run/user/$uid wpctl get-volume @DEFAULT_AUDIO_SINK@ >/root/qa-volume-before.txt
    cat /root/qa-volume-before.txt
    runuser -u toddlerbox -- env XDG_RUNTIME_DIR=/run/user/$uid wpctl set-volume --limit 1.0 @DEFAULT_AUDIO_SINK@ 0.80
    runuser -u toddlerbox -- env XDG_RUNTIME_DIR=/run/user/$uid wpctl set-mute @DEFAULT_AUDIO_SINK@ 0
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
            qa.wait_text('Music', 'Autoplay')
            time.sleep(4)
            qa.wait_audio()
            qa.shot('music-0.5.1')
            # Free Play and a four-second manual hold: actual supervised Cage input
            # and guest HDA output, separate from headless native worker tests.
            margin = max(12, min(24, w//44)); rail = max(170, min(236, round(w*.23)))
            # Deliberate slow mouse tap under TCG; verify the resulting UI state
            # rather than assuming the QMP click has already reached the app.
            module.command('input-send-event', {'events':[
                {'type':'abs','data':{'axis':'x','value':round((rail//2)*32767/(w-1))}},
                {'type':'abs','data':{'axis':'y','value':round((h-margin-137)*32767/(h-1))}}]})
            time.sleep(.5)
            module.command('input-send-event', {'events':[{'type':'btn','data':{'down':True,'button':'left'}}]})
            time.sleep(.5)
            module.command('input-send-event', {'events':[{'type':'btn','data':{'down':False,'button':'left'}}]})
            until = time.monotonic() + 20
            while time.monotonic() < until:
                visible = qa.text()
                picture = Image.open(qa.shot('free-play-state'))
                from toddlerbox.ui import theme
                selected = picture.getpixel((margin+10, h-margin-166+9))[:3] == theme.SELECTED
                if selected and 'autoplay' not in visible:
                    break
                time.sleep(.5)
            else:
                qa.shot('free-play-not-entered')
                raise AssertionError('Free Play UI did not activate')
            qa.shot('free-play-0.5.1')
            def fresh_rms(start):
                path = out/'audio.wav';size=path.stat().st_size
                with path.open('rb') as stream:
                    stream.seek(max(start, size-96000))
                    values = array('h', stream.read())
                if sys.byteorder != 'little':values.byteswap()
                return math.sqrt(sum(v*v for v in values)/max(1,len(values))), size-start
            start_audio = (out/'audio.wav').stat().st_size
            time.sleep(3)
            energy, fresh_bytes = fresh_rms(start_audio)
            print(f'Free Play PCM: {fresh_bytes} fresh bytes, RMS {energy}', flush=True)
            assert fresh_bytes > 0 and energy < 5, 'Free Play needs captured fresh silence'
            keyx, keyy = rail+margin*2+(w-rail-margin*3)//2, h-margin-35
            module.command('input-send-event', {'events':[
                {'type':'abs','data':{'axis':'x','value':round(keyx*32767/(w-1))}},
                {'type':'abs','data':{'axis':'y','value':round(keyy*32767/(h-1))}},
                {'type':'btn','data':{'down':True,'button':'left'}}]})
            start_audio = (out/'audio.wav').stat().st_size
            time.sleep(4)
            energy, fresh_bytes = fresh_rms(start_audio)
            assert fresh_bytes > 96000 and energy > 10, 'Held piano must still sound after four seconds'
            qa.shot('held-piano-0.5.1')
            module.command('input-send-event', {'events':[{'type':'btn','data':{'down':False,'button':'left'}}]})
            time.sleep(1)
            start_audio = (out/'audio.wav').stat().st_size
            time.sleep(1)
            energy, fresh_bytes = fresh_rms(start_audio)
            print(f'Released piano PCM: {fresh_bytes} fresh bytes, RMS {energy}', flush=True)
            assert fresh_bytes > 0 and energy < 5, 'Released piano needs captured fresh silence'
            qa.key('ctrl-alt-home', 2500)
            qa.mode('parent')
            print('QA: explicit rollback', flush=True)
            print(diagnostic('toddlerbox-maintenance --action rollback'), flush=True)
            print(diagnostic('''
    /opt/toddlerbox/current/.venv/bin/python -B -c "import importlib.metadata; assert importlib.metadata.version('ToddlerBox')=='0.5.0'"
    sha256sum -c /root/appliance-qa/creations.sha256
    test -f /usr/local/lib/toddlerbox-system/tbx_sync/usb_setup.py
    grep '^dns=default' /etc/NetworkManager/conf.d/90-toddlerbox-dns.conf
    '''), flush=True)
            install('/qa', 4)
            # Explicit opt-in changed config, so pin its new durable bytes for repeat checks.
            observe_accept('reinstalled-0.5.1')
            diagnostic('toddlerbox-mode child')
            qa.wait_health()
            module.command('system_reset')
            time.sleep(10)
            qa.wait_health()
            qa.shot('rebooted-0.5.1')
            diagnostic('sha256sum -c /root/appliance-qa/creations.sha256')
        # Escape remains independent even when the entire launcher is stopped.
        def freeze_launcher():
            # wait_health alone can see the pre-reset status file. Require an
            # actual current launcher, pinned by the production pidfd helper.
            print(diagnostic("""
PYTHONPATH=/usr/local/lib/toddlerbox-system python3 -B - <<'INNER'
import os, signal, subprocess, time
from pathlib import Path
from controller import launcher_processes
uid=int(subprocess.check_output(['id','-u','toddlerbox']))
for attempt in range(90):
    processes=launcher_processes(uid)
    try:
        if len(processes)==1:
            pid,fd=next(iter(processes.items()))
            signal.pidfd_send_signal(fd,signal.SIGSTOP)
            Path('/root/qa-frozen-pid').write_text(str(pid))
            print('Stopped current launcher',pid)
            break
    finally:
        for fd in processes.values():os.close(fd)
    time.sleep(1)
else:
    subprocess.run(['ps','-u','toddlerbox','-o','pid,args'])
    raise AssertionError('No unique current launcher after boot')
INNER
""",timeout=180), flush=True)
        freeze_launcher()
        qa.key('ctrl-alt-home', 2500)
        qa.mode('parent')
        print(diagnostic("""
PYTHONPATH=/usr/local/lib/toddlerbox-system python3 -B - <<'INNER'
import os, subprocess, time
from controller import launcher_processes
uid=int(subprocess.check_output(['id','-u','toddlerbox']))
for attempt in range(90):
    processes=launcher_processes(uid)
    for fd in processes.values():os.close(fd)
    if not processes and subprocess.run(['systemctl','is-active','--quiet','gdm3']).returncode==0:
        print('Stopped launcher gone; GDM active')
        break
    time.sleep(1)
else:raise AssertionError('Parent escape did not finish launcher shutdown and GDM restart')
INNER
"""), flush=True)
        qa.wait_text('Parent')
        qa.shot('stopped-app-parent-escape')
        diagnostic('toddlerbox-mode child')
        qa.wait_health()
        freeze_launcher()
        diagnostic("for i in $(seq 1 90); do pid=$(pgrep -u toddlerbox -f 'python.*toddlerbox.launcher' || true); if test -n \"$pid\" && test \"$pid\" != \"$(cat /root/qa-frozen-pid)\"; then exit 0; fi; sleep 1; done; exit 1", timeout=150)
        qa.wait_health()
        qa.shot('watchdog-recovered-0.5.1')
        diagnostic('sha256sum -c /root/appliance-qa/creations.sha256; sha256sum -c /root/qa-config.sha256')
        (out/'results.json').write_text(json.dumps({
            'platform':'Ubuntu24.04 x86-64 Q35 TCG, 2CPU 2GiB, no NIC, virtual HDA; direct-kernel boot of disposable overlay on qualified0.5.0 checkpoint',
            'checks':['signed0.5.1 update over qualified0.5.0 and genuine supervised acceptance',
                      'native Python3.12.3 bounded workers, durable saves and authenticated deferred IPC',
                      'full immutable release tree preserved by parent status; config bytes unchanged',
                      'explicit parent wpctl volume; song PCM and four-second held key/release through Cage',
                      'independent Ctrl+Alt+Home escape: stopped launcher exits and actual Parent greeter appears',
                      'explicit rollback to0.5.0; signed0.5.1 reinstall and accepted reboot',
                      'watchdog restarts a stopped launcher and recovers child frames',
                      'synthetic Paint/Typing exact SHA and config preservation through all transitions'],
            'limits':['no new ISO/fresh installation or physical HP touch/speaker calibration',
                      'VM QMP pointer is emulated mouse input; real FINGER regressions covered separately',
                      'future-image ALSA/PulseAudio diagnostic packages not installed by this bundle',
                      'unchanged2s startup helper deadline expires under slowTCG for genuine0.5.0 and0.5.1; PCM checks use explicit parent80percent volume']}, indent=2)+'\n')
        print('PATCH_UPDATE_VM_PASS', flush=True)
    finally:
        qa.stop()


if __name__ == '__main__':
    main()
