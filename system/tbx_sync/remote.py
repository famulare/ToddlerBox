"""Small copy-only rclone adapter. No remote delete/move/sync operation exists."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from .safeio import MAX_FILE, parts, reserve


class TransferError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class Rclone:
    def __init__(self, paths, root_id, stage, *, deadline, binary='/usr/bin/rclone', minimum=512*1024**2):
        self.paths, self.stage, self.deadline = paths, Path(stage), deadline
        self.minimum = minimum
        self.args = [binary, '--config', str(paths.config/'rclone.conf'),
                     '--drive-root-folder-id', root_id, '--transfers', '1', '--checkers','1',
                     '--retries','1','--low-level-retries','2','--contimeout','10s','--timeout','30s',
                     '--cache-dir',str(paths.state/'cache'), '--log-level','ERROR']

    def remote(self, path):
        parts(path)
        return 'toddlerbox:' + path

    def command(self, arguments, *, target=None, missing=False):
        if time.monotonic() >= self.deadline:
            raise TransferError('timed-out')
        # Output files stay private and bounded; never surface raw provider errors
        # or URLs/tokens in public logs, status, or the child UI.
        with tempfile.TemporaryFile(dir=self.stage) as output, tempfile.TemporaryFile(dir=self.stage) as error:
            environment = {'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8',
                           'XDG_CACHE_HOME':str(self.paths.state/'cache')}
            process = subprocess.Popen(self.args+arguments, stdout=output, stderr=error,
                                       stdin=subprocess.DEVNULL, env=environment)
            try:
                while process.poll() is None:
                    if time.monotonic() >= self.deadline:
                        raise TransferError('timed-out')
                    if os.fstat(output.fileno()).st_size > 4*1024**2 or os.fstat(error.fileno()).st_size > 65536:
                        raise TransferError('response-limit')
                    reserve(output.fileno(), minimum=self.minimum)
                    if target is not None and target.exists() and target.stat().st_size > MAX_FILE:
                        raise TransferError('file-limit')
                    time.sleep(.1)
                output.seek(0)
                result = output.read(4*1024**2 + 1)
                error.seek(0)
                diagnostics = error.read(65536).lower()
                if len(result) > 4*1024**2:
                    raise TransferError('response-limit')
                if process.returncode:
                    if missing and process.returncode in {3,4}:
                        return None
                    if any(word in diagnostics for word in (b'invalid_grant',b'unauthorized',b'401',b'token expired',b'invalid_client')):
                        raise TransferError('authorization-required')
                    if any(word in diagnostics for word in (b'network is unreachable',b'no such host',b'dial tcp',b'timeout',b'no route')):
                        raise TransferError('offline-or-unreachable')
                    raise TransferError('transfer-failed')
                return result
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

    def list(self, path, *, recursive=False):
        result = self.command(['lsjson',self.remote(path),'--hash','--max-depth','3' if recursive else '1'] +
                              (['--recursive'] if recursive else []), missing=True)
        if result is None:
            return []
        entries = json.loads(result)
        if not isinstance(entries, list) or len(entries) > 8192:
            raise TransferError('listing-limit')
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('Path'),str):
                raise TransferError('invalid-listing')
            parts(entry['Path'])
        return entries

    def get(self, remote, destination):
        self.command(['copyto',self.remote(remote),str(destination),'--checksum'], target=Path(destination))
        if not Path(destination).is_file() or Path(destination).stat().st_size > MAX_FILE:
            raise TransferError('download-limit')

    def put(self, source, remote, *, immutable=False):
        self.command(['copyto',str(source),self.remote(remote),'--checksum'] + (['--immutable'] if immutable else []))

    def verify(self, remote, expected):
        with tempfile.TemporaryDirectory(dir=self.stage) as check:
            destination = Path(check)/'verified'
            self.get(remote, destination)
            with destination.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest() != expected:
                    raise TransferError('remote-checksum-mismatch')
