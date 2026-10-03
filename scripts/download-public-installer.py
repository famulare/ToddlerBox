#!/usr/bin/env python3
"""Reassemble a checksum-identified public ISO from temporary GitHub Git blobs.

Use only the reviewed manifest provided with the candidate; these unattached
objects are a temporary transport, not durable release hosting. The recipient
should publish the verified ISO as a normal release asset. Requires authenticated
`gh` (the many chunk requests exceed GitHub's unauthenticated rate budget).
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


def download(manifest_path, output):
    manifest=json.loads(Path(manifest_path).read_text())
    if (manifest.get('version')!=1 or manifest.get('repository')!='famulare/ToddlerBox'
            or not re.fullmatch('[0-9a-f]{64}',manifest.get('sha256',''))
            or manifest.get('filename')!='toddlerbox-installer.iso'):
        raise ValueError('Unexpected public installer manifest')
    chunks=manifest['chunks']
    if (not 1<=len(chunks)<=1024 or sum(c['size'] for c in chunks)!=manifest['size']
            or not 0<manifest['size']<=4*1024**3):
        raise ValueError('Incomplete or oversized manifest')
    for index,chunk in enumerate(chunks):
        if (chunk['index']!=index or not 0<chunk['size']<=16*1024**2
                or not re.fullmatch('[0-9a-f]{40}',chunk['git_sha'])
                or not re.fullmatch('[0-9a-f]{64}',chunk['sha256'])):
            raise ValueError('Invalid chunk entry')
    output=Path(output)
    if output.exists():
        with output.open('rb') as current:
            if hashlib.file_digest(current,'sha256').hexdigest()==manifest['sha256']:
                print('Existing ISO verified:',output);return
        raise ValueError('Existing output differs; preserved')
    partial=output.with_name(output.name+'.part')
    fd=os.open(partial,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+b') as destination:
        if os.fstat(destination.fileno()).st_nlink!=1:
            raise ValueError('Transfer must be a single-link file')
        whole=hashlib.sha256()
        for index,chunk in enumerate(chunks):
            offset=destination.tell()
            data=destination.read(chunk['size'])
            if len(data)!=chunk['size'] or hashlib.sha256(data).hexdigest()!=chunk['sha256']:
                destination.seek(offset);destination.truncate()
                for attempt in range(3):
                    result=subprocess.run(['gh','api',f"repos/{manifest['repository']}/git/blobs/{chunk['git_sha']}"],
                                          stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    if result.returncode==0:break
                    if attempt==2:raise RuntimeError('GitHub download failed; authenticated gh access is required')
                    time.sleep(2*(attempt+1))
                body=json.loads(result.stdout)
                if body.get('sha')!=chunk['git_sha'] or body.get('encoding')!='base64':
                    raise ValueError('Unexpected GitHub blob response')
                data=base64.b64decode(''.join(body['content'].split()),validate=True)
                if len(data)!=chunk['size'] or hashlib.sha256(data).hexdigest()!=chunk['sha256']:
                    raise ValueError('Chunk verification failed')
                destination.write(data);destination.flush();os.fsync(destination.fileno())
            whole.update(data)
            print(f'Verified chunk {index+1}/{len(chunks)}',flush=True)
        destination.truncate()
        if destination.tell()!=manifest['size'] or whole.hexdigest()!=manifest['sha256']:
            raise ValueError('Complete ISO checksum or size mismatch')
        destination.flush();os.fsync(destination.fileno())
    # Exclusive final publication; preserve any file created while downloading.
    os.link(partial,output,follow_symlinks=False)
    partial.unlink()
    print(manifest['sha256'],output)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    download(args.manifest,args.output)
