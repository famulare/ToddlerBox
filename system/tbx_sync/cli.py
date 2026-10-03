from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import uuid

from .install import restore_archives, setup
from .safeio import atomic_json
from .state import Paths, finalize, initialize, load


def service_state():
    result = subprocess.run(['systemctl','show','toddlerbox-sync.service','--property=ActiveState,Result'],
                            capture_output=True,text=True,check=False,timeout=3)
    return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)


def status(paths):
    value = load(paths.state/'status.json',{'state':'never-run','last_success':None})
    unit = service_state()
    # Truthful even after an abrupt kill or a full disk prevented ExecStopPost
    # from updating the persistent record. Preserve its last success in memory.
    if value.get('state')=='running' and unit.get('ActiveState') not in {'active','activating','deactivating'}:
        value['state']='timed_out' if unit.get('Result')=='timeout' else 'interrupted'
        value['status_reconciled_from_systemd']=True
    value['service']=unit
    return value


def run():
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as client:
            client.bind('\0toddlerbox-mode-'+uuid.uuid4().hex)
            client.setsockopt(socket.SOL_SOCKET,socket.SO_PASSCRED,1)
            client.settimeout(2)
            client.sendto(b'sync','/run/toddlerbox-control.sock')
            message,ancillary,flags,_ = client.recvmsg(128,socket.CMSG_SPACE(12))
            root = any(level==socket.SOL_SOCKET and kind==socket.SCM_CREDENTIALS
                       and len(value)>=12 and struct.unpack('3i',value[:12])[1]==0
                       for level,kind,value in ancillary)
            if root and not flags & (socket.MSG_TRUNC|socket.MSG_CTRUNC) and message==b'OK':
                return
    except OSError:
        pass
    subprocess.run(['systemctl','start','--no-block','toddlerbox-sync.service'],check=True,timeout=5)


def main():
    parser=argparse.ArgumentParser(description='Parent-initiated private ToddlerBox Drive copies')
    parser.add_argument('command',choices=['setup','run','status','reconnect','import','finalize'])
    parser.add_argument('package',nargs='?')
    parser.add_argument('--sha256')
    parser.add_argument('--consume',action='store_true')
    parser.add_argument('--restore-directory',type=Path)
    args=parser.parse_args()
    if os.geteuid()!=0:
        parser.error('Use sudo or the parent desktop entry')
    paths=Paths()
    try:
        initialize(paths)
        if args.command=='finalize':
            finalize(paths,os.environ.get('SERVICE_RESULT','unknown'))
            return
        if args.command=='run':
            run()
            print('Sync requested. Run toddlerbox-sync status for the result.')
        elif args.command=='status':
            print(json.dumps(status(paths),indent=2))
        elif args.command=='import' and args.restore_directory:
            if not args.sha256:
                parser.error('--sha256 must identify the downloaded manifest.json')
            print(json.dumps(restore_archives(paths,args.restore_directory,args.sha256),indent=2))
        else:
            package=args.package
            expected=args.sha256
            if sys.stdin.isatty():
                package=package or input('Private setup package path: ').strip()
                expected=expected or input('Independently checked package SHA-256: ').strip()
            if not package or not expected:
                parser.error('Package and --sha256 are required')
            print(json.dumps(setup(paths,package,expected,consume=args.consume,
                                   reconnect=args.command=='reconnect'),indent=2))
    except BlockingIOError:
        print('A sync or import is already running. Try again after it completes.',file=sys.stderr)
        raise SystemExit(2)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
        # Never echo token-bearing parser/provider diagnostics.
        print('Operation refused or incomplete. Check the package, checksum, available disk space, and sync status. Existing work and transfer package are preserved.',file=sys.stderr)
        raise SystemExit(1)
    if sys.stdin.isatty():
        input('Press Enter to close.')


if __name__=='__main__':
    main()
