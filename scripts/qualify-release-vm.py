"""Fresh-install x86-64 VM smoke qualification using synthetic work only.

Runs on an isolated builder with Docker image toddlerbox-image-tools and Tesseract.
Never opens physical disks. The ephemeral parent password is kept in memory;
only explicitly selected screenshots/results are published, never VM disks.
"""
from __future__ import annotations

import argparse
from array import array
import base64
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import subprocess
import sys
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'system'))
from qmp import command


class Qualification:
    def __init__(self, image, out):
        self.image, self.out = image.resolve(), out.resolve()
        if self.out.exists():
            raise ValueError('Use a new qualification directory; preserve previous evidence')
        self.out.mkdir(parents=True)
        os.environ['TODDLERBOX_VM_DIR']=str(self.out)
        self.password=secrets.token_hex(10)
        self.name='toddlerbox-release-qa'
        self.results=[]
        self.authenticated=False

    def docker(self,*args,**kwargs):
        return subprocess.run(['docker',*args],check=True,**kwargs)

    def start(self,installer=False):
        if installer:
            self.docker('run','--rm','--network=none','-v',f'{self.out}:/vm','toddlerbox-image-tools',
                        'bash','-c',f'cp /usr/share/OVMF/OVMF_VARS_4M.fd /vm/OVMF.fd; qemu-img create -f qcow2 /vm/target.qcow2 16G; chown -R {os.getuid()}:{os.getgid()} /vm')
        media=['-cdrom','/build/toddlerbox-installer.iso','-boot','d'] if installer else []
        # Use software CPU emulation intentionally: this evidence never assumes nested KVM.
        self.docker('run','-d','--name',self.name,'--user',f'{os.getuid()}:{os.getgid()}',
                    '--network=none','-v',f'{self.image}:/build:ro','-v',f'{self.out}:/vm',
                    'toddlerbox-image-tools','qemu-system-x86_64','-accel','tcg,thread=multi',
                    '-machine','q35','-cpu','qemu64','-smp','2','-m','4096',
                    '-drive','if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd',
                    '-drive','if=pflash,format=raw,file=/vm/OVMF.fd',
                    '-drive','if=virtio,format=qcow2,discard=unmap,detect-zeroes=unmap,file=/vm/target.qcow2',
                    '-device','virtio-vga','-device','qemu-xhci','-device','usb-tablet','-nic','none',
                    '-audiodev','wav,id=audio,path=/vm/audio.wav','-device','ich9-intel-hda',
                    '-device','hda-duplex,audiodev=audio','-display','none',
                    '-qmp','unix:/vm/qmp.sock,server=on,wait=off',
                    '-chardev','socket,id=serial,path=/vm/serial.sock,server=on,wait=off,logfile=/vm/serial.log',
                    '-serial','chardev:serial',*media,stdout=subprocess.DEVNULL)

    def stop(self):
        subprocess.run(['docker','rm','-f',self.name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def key(self,name,hold=50):
        command('human-monitor-command',{'command-line':f'sendkey {name} {hold}'})
        time.sleep(.12)

    def type(self,text):
        for char in text:
            self.key(char)
            time.sleep(.15)  # Let a software-emulated console consume each key.
        self.key('ret')

    def shot(self,name):
        command('screendump',{'filename':f'/vm/{name}.ppm'})
        path=self.out/f'{name}.png'
        Image.open(self.out/f'{name}.ppm').save(path)
        return path

    def text(self):
        path=self.shot('probe')
        # Sparse icon captions are missed by default page segmentation.
        picture=Image.open(path)
        path=self.out/'ocr-probe.png'
        picture.resize((picture.width*2,picture.height*2)).save(path)
        return subprocess.check_output(['tesseract',str(path),'stdout','--psm','11'],stderr=subprocess.DEVNULL,text=True).lower()

    def wait_text(self,*words,timeout=360):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:
                value=self.text()
                if all(word.lower() in value for word in words):
                    return value
            except (OSError,RuntimeError,ValueError,subprocess.CalledProcessError):
                pass
            time.sleep(2)
        raise TimeoutError(f'VM screen did not reach expected labels {words}')

    def click(self,x,y):
        image=Image.open(self.shot('probe'))
        command('input-send-event',{'events':[
            {'type':'abs','data':{'axis':'x','value':round(x*32767/(image.width-1))}},
            {'type':'abs','data':{'axis':'y','value':round(y*32767/(image.height-1))}}]})
        time.sleep(.2)
        for down in (True,False):
            command('input-send-event',{'events':[{'type':'btn','data':{'down':down,'button':'left'}}]})
            time.sleep(.12)

    def until(self,conn,pattern,timeout=180):
        data=b''; end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:
                part=conn.recv(65536)
            except socket.timeout:
                continue
            if not part: raise RuntimeError('VM serial console closed')
            data+=part
            if re.search(pattern,data): return data
        raise TimeoutError('Independent serial prompt timeout (contents withheld)')

    def install(self):
        self.start(installer=True)
        try:
            self.wait_text('Install ToddlerBox','serial console')
        except TimeoutError:
            self.shot('installer')  # Safe: no password has been entered yet.
            raise
        self.shot('installer')
        self.key('down');self.key('ret')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.settimeout(1);conn.connect(str(self.out/'serial.sock'))
            text=self.until(conn,b'Target whole disk',600)
            assert b'/dev/vda' in text and b'toddlerbox.img.zst: OK' in text
            # The only disk is the fresh disposable target created above.
            conn.sendall(b'/dev/vda\n');self.until(conn,b'type exactly ERASE /dev/vda:')
            conn.sendall(b'ERASE /dev/vda\n');self.until(conn,b'Press Enter to power off.',900)
            conn.sendall(b'\n')
        self.docker('wait',self.name,timeout=90,stdout=subprocess.DEVNULL)
        self.stop()
        self.results.append('fresh ISO installation, payload checksum and exact target confirmation')
        self.start()
        self.wait_text('new password')
        self.shot('first-boot-password')
        self.type(self.password)
        # Console font OCR is unreliable for the confirmation prompt.
        # The next stage must authenticate with this password on ttyS0 and
        # verify the durable password-created marker, rather than infer success.
        time.sleep(3)
        self.type(self.password)
        time.sleep(8)

    def serial(self,script,timeout=180):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.settimeout(.5);conn.connect(str(self.out/'serial.sock'))
            conn.sendall(b'\r')
            state=self.until(conn,rb'login:|TBXQA#|parent@|root@',180)
            if b'login:' in state:
                conn.sendall(b'parent\n');self.until(conn,b'Password:')
                conn.sendall(self.password.encode()+b'\n');self.until(conn,b'parent@');state=b'parent@'
            if b'parent@' in state:
                conn.sendall(b"sudo -S -p '__SU''DO__' bash\n")
                reply=self.until(conn,rb'__SUDO__|root@')
                if b'__SUDO__' in reply:
                    conn.sendall(self.password.encode()+b'\n');self.until(conn,b'root@')
            marker=secrets.token_hex(6)
            sync=f'__SYNC_{marker}__'
            done=f'__DONE_{marker}__'
            conn.sendall(("stty -echo; PS1='TBX''QA# '; printf '\\n"+sync+"\\n'\n").encode())
            self.until(conn,re.escape(sync.encode())+rb'\r?\n')
            encoded=base64.b64encode(('set -e\n'+script).encode()).decode()
            conn.sendall((f"bash -c \"$(printf %s {encoded} | base64 -d)\"; printf '\\n{done}%s\\n' \"$?\"\n").encode())
            reply=self.until(conn,re.escape(done.encode())+rb'\d+\r?\n',timeout)
            status=int(re.search(re.escape(done.encode())+rb'(\d+)',reply)[1])
            if status:
                print(reply.decode(errors='replace').replace(self.password,'[redacted]'),flush=True)
                raise RuntimeError(f'VM diagnostic failed, exit {status}')
            self.authenticated=True
            return reply.decode(errors='replace').replace(self.password,'[redacted]')

    def mode(self,expected):
        self.serial(f'for i in $(seq 1 60); do test "$(cat /run/toddlerbox-system/mode)" != {expected} || exit 0; sleep 1; done; exit 1')

    def wait_health(self):
        self.serial('for i in $(seq 1 120); do if python3 -c \'import json; s=json.load(open("/run/toddlerbox-system/status.json")); assert s["mode"]=="child" and s.get("seen_frame")\'; then exit 0; fi; sleep 1; done; exit 1',timeout=210)

    def rms(self,seconds=2):
        path=self.out/'audio.wav'
        with path.open('rb') as stream:
            header=stream.read(4096);start=header.index(b'data')+8
            rate=struct.unpack_from('<I',header,24)[0];channels=struct.unpack_from('<H',header,22)[0]
            size=path.stat().st_size
            stream.seek(max(start,size-round(seconds*rate*channels*2)))
            values=array('h',stream.read((size-stream.tell())//2*2))
        if sys.byteorder!='little':values.byteswap()
        return math.sqrt(sum(v*v for v in values)/max(1,len(values)))

    def home(self):
        size=Image.open(self.shot('probe')).size
        self.click(size[0]-36,45)
        self.wait_text('Paint','Math','Reading')

    def wait_audio(self):
        # Software emulation does not promise a fixed wall-time/guest-audio
        # offset. Require actual recorded PCM, bounded by eight seconds.
        end=time.monotonic()+8
        while time.monotonic()<end:
            if self.rms(.5)>10:
                return
            time.sleep(.15)
        raise AssertionError('No audible PCM after deliberate speech tap')

    def smoke(self):
        self.serial('''
        test -e /var/lib/toddlerbox-system/password-created
        test ! -e /var/lib/toddlerbox-system/setup-complete
        test "$(cat /run/toddlerbox-system/mode)" = parent
        if toddlerbox-mode child; then exit 1; fi
        for unit in toddlerbox-controller NetworkManager gdm3; do systemctl is-active --quiet "$unit"; done
        test "$(systemctl is-enabled toddlerbox-sync.service 2>/dev/null || true)" = static
        test -z "$(systemctl list-timers --all --no-legend | grep toddlerbox-sync || true)"
        test -z "$(ip -o link show | grep -v 'lo:')"
        test -x /usr/local/libexec/toddlerbox-cage
        test "$(stat -c %a /var/lib/toddlerbox-system)" = 700
        /opt/toddlerbox/current/.venv/bin/python - <<'INNER'
from toddlerbox.config import load_config
from toddlerbox.music.library import load_library
from toddlerbox.math.speech import NumberBank
from unittest.mock import Mock
from pathlib import Path
import importlib.metadata
assert importlib.metadata.version('ToddlerBox')=='0.4.0'
import os
os.environ['KIDBOX_CONFIG']='/etc/toddlerbox/config.yaml'
assert len(load_config()['launcher']['apps'])==6
assert len(load_library(Path('/opt/toddlerbox/current/assets/music'),Mock())[0])==18
assert all(NumberBank(Mock()).get(n) for n in range(101))
assert all(NumberBank(Mock()).operator(n) for n in ('plus','minus','equals'))
INNER
        toddlerbox-maintenance --action test
        ''')
        self.wait_text('Paint','Math','Reading')
        self.wait_health()
        self.shot('six-activity-launcher')
        size=Image.open(self.out/'six-activity-launcher.png').size
        w,h=size
        icon=max(120,min(184,int(min(size)*.23)));gap=int(icon*.3)
        left=w//2-(3*icon+2*gap)//2;top=h//2-(2*icon+gap)//2
        centers=[(left+(i%3)*(icon+gap)+icon//2,top+(i//3)*(icon+gap)+icon//2) for i in range(6)]
        # Music: reach last song with wheel, keep Free Play reachable and verify real HDA PCM.
        self.click(*centers[2]);self.wait_text('Music','Autoplay')
        time.sleep(4);assert self.rms()>10
        self.shot('music-first-song')
        self.click(90,240)
        for _ in range(18):
            command('input-send-event',{'events':[{'type':'btn','data':{'down':True,'button':'wheel-down'}},{'type':'btn','data':{'down':False,'button':'wheel-down'}}]})
        time.sleep(1);self.shot('music-scrolled')
        margin=max(12,min(24,w//44));rail=max(170,min(236,round(w*.23)))
        list_bottom=h-margin-174
        self.click(90,list_bottom-29);self.wait_text('New World Largo')
        time.sleep(4);assert self.rms()>10
        self.shot('music-largo')
        self.click(90,h-margin-137);time.sleep(3);assert self.rms()<1
        self.shot('music-free-play')
        keyboard=__import__('pygame').Rect(rail+margin*2,h-margin-min(150,h//4),w-rail-margin*3,min(150,h//4))
        from toddlerbox.music.visuals import piano_keys
        self.click(*piano_keys(keyboard,48,72)[60].center)
        self.home();time.sleep(3);assert self.rms()<1
        self.results.append('18-song library, scroll to last song, Free Play, HDA song output and Home silence')
        # Math: pictures first, silent reveal, explicit bundled speech, cleanup.
        self.click(*centers[5]);self.wait_text('Math','Numbers')
        self.shot('math-objects-first')
        self.click((w-128)//2+24,152);self.shot('math-revealed')
        time.sleep(2);assert self.rms()<1
        self.click(w//2+125,45);self.wait_audio()
        self.shot('math-speaking')
        self.click(w//2,45);self.click((w-128)//2+24,152)
        time.sleep(3);assert self.rms()<1
        self.click(w//2+125,45);self.wait_audio()
        self.shot('math-equation');self.home();time.sleep(3);assert self.rms()<1
        self.results.append('Math pictures-first, silent reveal, explicit number/equation HDA output, validated operator clips and Home silence')
        for i,title in ((0,'Paint'),(1,'Photos'),(3,'Typing'),(4,'Reading')):
            self.click(*centers[i]);time.sleep(2)
            if title == 'Reading': self.wait_text(title)
            self.shot(title.lower());self.home()
        self.serial('for i in $(seq 1 40); do test ! -e /run/toddlerbox-system/setup-test-observed || exit 0; sleep 1; done; exit 1')
        self.key('ctrl-alt-home',2500);time.sleep(5);self.mode('parent');self.shot('authenticated-parent-greeter')
        self.serial('''
        test -e /run/toddlerbox-system/setup-recovery-observed
        toddlerbox-maintenance --action check network skipped
        toddlerbox-maintenance --action check audio passed
        toddlerbox-maintenance --action check input passed
        toddlerbox-maintenance --action check recovery passed
        toddlerbox-maintenance --action check drive skipped
        toddlerbox-maintenance --action finish
        toddlerbox-mode child
        ''')
        self.wait_text('Paint','Math','Reading');self.wait_health()
        self.serial("pid=$(pgrep -u toddlerbox -f '^([^ ]*/)?python[0-9.]* -m toddlerbox[.]launcher$'); test -n \"$pid\"; kill -STOP $pid")
        self.key('ctrl-alt-home',2500);time.sleep(6);self.mode('parent')
        self.shot('frozen-app-parent-recovery')
        self.serial('toddlerbox-mode child');self.wait_text('Paint','Math','Reading');self.wait_health()
        self.serial("pid=$(pgrep -u toddlerbox -f '^([^ ]*/)?python[0-9.]* -m toddlerbox[.]launcher$'); test -n \"$pid\"; printf %s $pid >/root/qa-old-pid; python3 -c 'import json; open(\"/root/qa-old-restarts\",\"w\").write(str(json.load(open(\"/run/toddlerbox-system/status.json\"))[\"restarts\"]))'; kill -STOP $pid")
        self.serial("""
        old=$(cat /root/qa-old-pid)
        for i in $(seq 1 90); do
            new=$(pgrep -u toddlerbox -f '^([^ ]*/)?python[0-9.]* -m toddlerbox[.]launcher$' || true)
            if test -n "$new" && test "$new" != "$old" && test ! -e "/proc/$old"; then
                if python3 -c 'import json; s=json.load(open("/run/toddlerbox-system/status.json")); assert s["restarts"] > int(open("/root/qa-old-restarts").read()) and s["seen_frame"]'; then exit 0; fi
            fi
            sleep 1
        done
        exit 1
        """,timeout=160)
        self.wait_text('Paint','Math','Reading');self.wait_health()
        self.shot('watchdog-recovered-launcher')
        self.results.append('supervised first setup, independent escape from stopped launcher and watchdog recovery')
        command('system_reset');time.sleep(15)
        self.wait_text('Paint','Math','Reading');self.wait_health();self.shot('rebooted-launcher')
        self.results.append('setup completion persists and reboot returns to supervised child session without network')
        self.serial('test -z "$(pgrep -u toddlerbox -f gnome-shell || true)"; test -n "$(pgrep -u toddlerbox -x toddlerbox-cage)"')
        self.results.append('standalone Cage child session with no child GNOME shell')
        (self.out/'results.json').write_text(json.dumps({'platform':'x86-64 Q35/UEFI/TCG, 2 CPUs, 4GB, no NIC, virtual HDA/USB tablet',
            'checks':self.results,'limits':['HP Wi-Fi/touch gestures/trackpad/speakers/sleep require physical acceptance',
             'OCR and QMP exercise virtual pointer/keyboard, not physical multi-touch',
             'Automated PCM checks do not establish human listening approval']},indent=2)+'\n')
        print(json.dumps(self.results),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image-dir',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    args=p.parse_args();q=Qualification(args.image_dir,args.output)
    try:
        q.install();print('Fresh installation and parent password completed',flush=True);q.smoke()
    except Exception:
        if q.authenticated:
            # Only after independent real parent authentication. Never capture
            # a failed password-entry screen or expose the raw serial log.
            q.shot('diagnostic-authenticated')
            try:
                print(q.serial('cat /run/toddlerbox-system/status.json; journalctl -b -u toddlerbox-controller -u gdm3 --no-pager -n 70; tail -60 /var/lib/toddlerbox/logs/toddlerbox.log 2>/dev/null || true'),flush=True)
            except Exception as error:
                print(f'Additional diagnostic unavailable: {type(error).__name__}',flush=True)
        result=subprocess.run(['docker','logs','--tail','60',q.name],capture_output=True,text=True)
        print((result.stdout+result.stderr).replace(q.password,'[redacted]'),flush=True)
        raise
    finally:
        q.stop()
        # Probe could be mid-password if a run failed. It is never a publication artifact.
        (q.out/'probe.png').unlink(missing_ok=True)
        (q.out/'probe.ppm').unlink(missing_ok=True)
        (q.out/'ocr-probe.png').unlink(missing_ok=True)


if __name__=='__main__':main()
