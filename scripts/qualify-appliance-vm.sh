#!/bin/bash
# Disposable VM ONLY, root on independent console. Uses synthetic work/fixtures.
# Mount the public qualification directory at /qa; never mount private host data.
set -euo pipefail
export PYTHONPATH=/usr/local/lib/toddlerbox-system
state=/var/lib/toddlerbox-system
case ${1:?inspect|fixtures|good|bad|pending|accepted|restored|interrupted|corrupt|repair|offline|grub} in
inspect)
    test -e "$state/password-created"
    test -e "$state/appliance-v1"
    test "$(stat -c %a "$state")" = 700
    systemctl is-active toddlerbox-controller NetworkManager gdm3
    test "$(cat /run/toddlerbox-system/mode)" = parent
    dpkg-query -W gh wpasupplicant rclone python3-cryptography
    systemctl is-enabled apt-daily.timer apt-daily-upgrade.timer | awk '{if ($0 != "masked") exit 1}'
    test -z "$(systemctl list-timers --all --no-legend | grep toddlerbox-sync || true)"
    python3 -c 'from appliance import progress; print(progress()); from release_client import sequence_guard; sequence_guard(1, __import__("pathlib").Path("/"))'
    ;;
fixtures)
    mkdir -p /root/appliance-qa
    printf 'synthetic durable work\n' >/var/lib/toddlerbox/qa-preserved.txt
    chown toddlerbox:toddlerbox /var/lib/toddlerbox/qa-preserved.txt
    sha256sum /var/lib/toddlerbox/qa-preserved.txt >/root/appliance-qa/work.sha256
    python3 - <<'PY'
import hashlib,json,zipfile
from pathlib import Path
controller=Path('/usr/local/lib/toddlerbox-system/controller.py').read_bytes()
for name,content in [('good',controller+b'\n# Disposable qualification candidate\n'),('bad',b'def incomplete(\n')]:
    value={'format':1,'source':{'git':'synthetic-fixture','content':'f'*16},'files':{'controller.py':hashlib.sha256(content).hexdigest()},'app':None}
    path=Path('/root/appliance-qa')/(name+'.pyz')
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('__main__.py','')
        archive.writestr('update_bundle.py','')
        archive.writestr('manifest.json',json.dumps(value))
        archive.writestr('payload/controller.py',content)
PY
    ;;
good|bad)
    FIXTURE="$1" python3 - <<'PY'
import os
from pathlib import Path
from update_bundle import run,sha
path=Path('/root/appliance-qa')/(os.environ['FIXTURE']+'.pyz')
print(run(path,sha(path)))
PY
    ;;
pending|accepted|restored)
    EXPECTED="$1" python3 - <<'PY'
import os
from pathlib import Path
from boot_recovery import latest
value=latest(Path('/'))[1]
expected={'pending':'pending','accepted':'accepted','restored':'rolled-back'}[os.environ['EXPECTED']]
assert value['status']==expected,value['status']
print({key:value.get(key) for key in ('status','attempts','observed')})
PY
    sha256sum -c /root/appliance-qa/work.sha256
    ;;
interrupted)
    python3 - <<'PY'
from pathlib import Path
from boot_recovery import atomic,latest,record
job,value=latest(Path('/'))
assert value['status']=='pending'
value['status']='applying'
record(job/'state.json',value)
atomic(Path('/var/lib/toddlerbox-system/maintenance'),b'synthetic interrupted installation\n')
atomic(Path('/usr/local/lib/toddlerbox-system/controller.py'),b'def incomplete(\n',0o644)
PY
    echo 'Reset the VM now; resident recovery must run before importing controller.'
    ;;
corrupt)
    python3 - <<'PY'
from pathlib import Path
from boot_recovery import latest
job,value=latest(Path('/'))
assert value['status']=='pending'
source=job/'controller.py'
Path('/root/appliance-qa/intact-backup').write_bytes(source.read_bytes())
source.write_bytes(b'synthetic corrupt backup')
PY
    echo 'Reset VM; parent recovery must refuse corrupt backup and keep Status usable.'
    ;;
repair)
    python3 - <<'PY'
from pathlib import Path
from boot_recovery import atomic,latest
job,value=latest(Path('/'))
atomic(job/'controller.py',Path('/root/appliance-qa/intact-backup').read_bytes(),0o644)
PY
    /usr/local/sbin/toddlerbox-maintenance --action recover
    ;;
offline)
    python3 - <<'PY'
from pathlib import Path
from release_client import catalog
before=Path('/var/lib/toddlerbox-system/release-sequence.json').read_bytes()
try:
    catalog()
except OSError:
    pass
else:
    raise AssertionError('Expected no-network failure')
assert Path('/var/lib/toddlerbox-system/release-sequence.json').read_bytes()==before
print('Offline metadata failure preserved installed trust state')
PY
    if /usr/local/sbin/toddlerbox-maintenance --action ubuntu; then
        echo 'Offline Ubuntu check must fail rather than record a successful online check'; exit 1
    fi
    test ! -e "$state/apt-maintenance"
    /usr/local/sbin/toddlerbox-maintenance --action status
    ;;
grub)
    update-grub
    grep -q 'ToddlerBox parent recovery' /boot/grub/grub.cfg
    grep -q 'toddlerbox.parent=1' /boot/grub/grub.cfg
    grep -q 'set timeout=5' /boot/grub/grub.cfg
    echo 'Ubuntu regeneration retained parent boot recovery'
    ;;
*) exit 2 ;;
esac
