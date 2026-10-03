#!/usr/bin/env python3
"""Run on the parent's Mac with uv. Never run real OAuth on the image builder."""
from __future__ import annotations

import argparse
import configparser
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'system'))
from tbx_sync.media import validate_photo
from tbx_sync.package import config_bytes, credentials_bytes
from tbx_sync.remote import Rclone
from tbx_sync.safeio import MAX_FILE, MAX_TOTAL, SafeTree, parts
from tbx_sync.state import Paths, private_directory


def outside_checkout(path):
    path=Path(path).absolute()
    checkout=Path(__file__).resolve().parents[1]
    if path.resolve().is_relative_to(checkout):
        raise ValueError('Private files must be outside the source checkout')
    return path


def write_private(path,data):
    with SafeTree(path.parent) as tree:
        expected=hashlib.sha256(tree.read(path.name,limit=65536)).hexdigest() if tree.exists(path.name) else None
        tree.publish(path.name,data,expected=expected,mode=0o600,minimum=0)


def authorize(directory,client_id,secret_file,binary):
    directory=outside_checkout(directory)
    private_directory(directory)
    path=directory/'rclone.conf'
    if path.exists():
        raise ValueError('Existing authorization preserved; use a new private directory for reconnect')
    secret_file=outside_checkout(secret_file)
    with SafeTree(secret_file.parent) as tree:
        secret=tree.read(secret_file.name,limit=1024).decode().strip()
    if any(c in client_id+secret for c in '\r\n[]'):
        raise ValueError('Invalid OAuth client fields')
    config=configparser.ConfigParser(interpolation=None)
    config['toddlerbox']={'type':'drive','client_id':client_id,'client_secret':secret,
                         'scope':'drive.readonly,drive.file','root_folder_id':''}
    output=io.StringIO();config.write(output)
    write_private(path,output.getvalue().encode())
    subprocess.run([binary,'--config',str(path),'config','reconnect','toddlerbox:','--auto-confirm'],check=True)
    def invoke(*arguments):
        return subprocess.check_output([binary,'--config',str(path),*arguments],stderr=subprocess.DEVNULL)
    before=json.loads(invoke('lsjson','toddlerbox:','--dirs-only','--max-depth','1'))
    if any(item.get('Name','').casefold()=='toddlerbox' for item in before):
        raise ValueError('ToddlerBox already exists; preserve it and explicitly reuse its verified rclone-created root ID')
    invoke('mkdir','toddlerbox:ToddlerBox')
    after=json.loads(invoke('lsjson','toddlerbox:','--dirs-only','--max-depth','1'))
    matches=[item for item in after if item.get('Name')=='ToddlerBox']
    if len(matches)!=1 or not matches[0].get('ID'):
        raise ValueError('Ambiguous newly created Drive folder')
    root=matches[0]['ID']
    # Pin the remote immediately after creating it. Routine helpers never use an
    # account-root remote. User setup must use Production consent before grant.
    config.read(path)
    config['toddlerbox']['root_folder_id']=root
    output=io.StringIO();config.write(output)
    normalized=credentials_bytes(output.getvalue().encode(),root)
    write_private(path,normalized)
    write_private(directory/'config.json',json.dumps({'version':1,'root_folder_id':root}).encode()+b'\n')
    for name in ['Photos','Creations','History','Initial backup']:
        invoke('mkdir','toddlerbox:'+name)
    print('Authorized private root. Credentials remain in the private directory.')


def originals(directory):
    if directory is None:
        return {}
    result,seen,total={},set(),0
    with SafeTree(directory) as tree:
        for name in sorted(tree.names()):
            # No flattening, ignored nested libraries, or ambiguous duplicates.
            if len(parts(name))!=1 or name.casefold() in seen or len(result)>=4096:
                raise ValueError('Invalid or duplicate photo filename')
            seen.add(name.casefold())
            data=tree.read(name)
            validate_photo(data,name)
            total+=len(data)
            if total>MAX_TOTAL:
                raise ValueError('Original photo set too large')
            result[name]={'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    return result


def package(directory,photos,output):
    directory,output=outside_checkout(directory),outside_checkout(output)
    photo_files=originals(photos)
    with SafeTree(directory) as tree:
        config=tree.read('config.json',limit=65536)
        root=config_bytes(config)['root_folder_id']
        credentials=credentials_bytes(tree.read('rclone.conf',limit=65536),root)
    files={'config.json':config,'rclone.conf':credentials}
    entries={name:{'size':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in files.items()}
    entries.update({'photos/library/'+name:record for name,record in photo_files.items()})
    manifest={'format':'toddlerbox-setup','version':1,'package_id':str(uuid.uuid4()),
              'created_at':dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),'files':entries}
    # Exclusive private creation; a failed write removes only this new archive.
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb') as raw, tarfile.open(fileobj=raw,mode='w:gz',format=tarfile.USTAR_FORMAT) as archive:
            def add(name,data):
                info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o600
                archive.addfile(info,io.BytesIO(data))
            add('manifest.json',json.dumps(manifest,sort_keys=True,indent=2).encode()+b'\n')
            for name,data in files.items():add(name,data)
            if photos is not None:
                with SafeTree(photos) as tree:
                    for name,record in photo_files.items():
                        data=tree.read(name)
                        if hashlib.sha256(data).hexdigest()!=record['sha256']:
                            raise ValueError('Original changed during packaging')
                        add('photos/library/'+name,data)
        with output.open('rb') as source:
            os.fsync(source.fileno())
            checksum=hashlib.file_digest(source,'sha256').hexdigest()
        print(checksum+'  '+str(output))
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def backup(directory,photos,binary,date):
    directory=outside_checkout(directory)
    records=originals(photos)
    config=config_bytes((directory/'config.json').read_bytes())
    credentials_bytes((directory/'rclone.conf').read_bytes(),config['root_folder_id'])
    dt.datetime.strptime(date,'%Y-%m-%d')
    with tempfile.TemporaryDirectory(dir=directory) as temporary, SafeTree(photos) as tree:
        stage=Path(temporary)
        remote=Rclone(Paths(directory,directory,Path(photos)),config['root_folder_id'],stage,
                      deadline=time.monotonic()+900,binary=binary)
        for name,record in records.items():
            data=tree.read(name)
            if hashlib.sha256(data).hexdigest()!=record['sha256']:
                raise ValueError('Original changed after verification')
            source=stage/name
            source.write_bytes(data)
            target='Initial backup/'+date+'/'+name
            remote.put(source,target,immutable=True)
            remote.verify(target,record['sha256'])
            source.unlink()
        manifest={'format':'toddlerbox-initial-photos','version':1,'files':records}
        source=stage/'manifest.json'
        source.write_bytes(json.dumps(manifest,sort_keys=True,indent=2).encode()+b'\n')
        remote.put(source,'Initial backup/'+date+'/manifest.json',immutable=True)
        remote.verify('Initial backup/'+date+'/manifest.json',hashlib.sha256(source.read_bytes()).hexdigest())
    print(f'Verified {len(records)} original photos in Initial backup/{date}; originals unchanged.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['authorize','package','backup'])
    parser.add_argument('--private-dir',required=True,type=Path)
    parser.add_argument('--photos',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--client-id')
    parser.add_argument('--client-secret-file',type=Path)
    parser.add_argument('--rclone',default=shutil.which('rclone'))
    parser.add_argument('--date',default=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d'))
    args=parser.parse_args()
    if args.command=='authorize':
        if not args.client_id or not args.client_secret_file or not args.rclone:
            parser.error('authorize needs --client-id, --client-secret-file and rclone')
        authorize(args.private_dir,args.client_id,args.client_secret_file,args.rclone)
    elif args.command=='package':
        if not args.output:parser.error('package needs --output')
        package(args.private_dir,args.photos,args.output)
    else:
        if not args.photos or not args.rclone:parser.error('backup needs --photos and rclone')
        backup(args.private_dir,args.photos,args.rclone,args.date)


if __name__=='__main__':
    main()
