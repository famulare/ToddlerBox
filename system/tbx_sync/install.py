from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

from .media import typing_text, validate_photo
from .package import consume_package, credentials_bytes, inspect_package
from .safeio import MAX_TOTAL, SafeTree, atomic_json, parts
from .state import initialize, load, lock, private_directory


def ensure_library(paths):
    with SafeTree(paths.data) as data:
        owner = os.fstat(data.fd)
        fd = os.dup(data.fd)
        try:
            for component in ['photos','library']:
                made = False
                try:
                    os.mkdir(component,0o755,dir_fd=fd)
                    made = True
                except FileExistsError:
                    pass
                child = os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                if made:
                    os.fchown(child,owner.st_uid,owner.st_gid)
                    os.fsync(child)
                    os.fsync(fd)
                os.close(fd)
                fd = child
        finally:
            os.close(fd)


def setup(paths, archive, expected, *, consume=False, reconnect=False, minimum=512*1024**2):
    initialize(paths)
    with lock(paths), tempfile.TemporaryDirectory(prefix='import-',dir=paths.state/'staging') as temporary:
        stage = Path(temporary)
        manifest, config, identity = inspect_package(archive,expected,stage,minimum=minimum)
        installed = load(paths.config/'installed.json')
        if installed:
            if reconnect:
                old = load(paths.config/'config.json')
                if old['root_folder_id'] != config['root_folder_id']:
                    raise ValueError('Reconnect cannot change the Drive root')
            elif installed.get('package_sha256') == expected:
                if consume:
                    consume_package(archive,identity)
                return {'result':'already-installed','photos_imported':0}
            else:
                raise ValueError('Already configured; use reconnect or the Photos folder')
        elif reconnect:
            raise ValueError('Setup is required before reconnect')
        credentials = credentials_bytes((stage/'rclone.conf').read_bytes(),config['root_folder_id'])
        photos = {name.removeprefix('photos/library/'):entry for name,entry in manifest['files'].items()
                  if name.startswith('photos/library/')}
        imported = 0
        if not reconnect:
            ensure_library(paths)
            # Check every collision before publishing any photo. Entries can still
            # race; the final link operation never replaces a racing destination.
            with SafeTree(paths.library) as library:
                existing = {name.casefold():name for name in library.names()}
                for name, entry in photos.items():
                    if name.casefold() in existing:
                        old_name = existing[name.casefold()]
                        old = library.read(old_name)
                        if old_name != name or hashlib.sha256(old).hexdigest() != entry['sha256']:
                            raise ValueError('Existing photo name conflict')
                private_directory(paths.state/'initial')
                private_directory(paths.state/'initial'/manifest['package_id'])
                with SafeTree(paths.state/'initial'/manifest['package_id']) as originals:
                    for name, entry in photos.items():
                        data = (stage/'photos/library'/name).read_bytes()
                        if not originals.exists(name):
                            originals.publish(name,data,mode=0o600,minimum=minimum)
                        elif hashlib.sha256(originals.read(name)).hexdigest() != entry['sha256']:
                            raise ValueError('Preserved original changed')
                        if name.casefold() not in existing:
                            library.publish(name,data,minimum=minimum)
                            imported += 1
                atomic_json(paths.state/'initial.json',{'version':1,'package_id':manifest['package_id'],
                            'date':manifest['created_at'][:10],'files':photos,'complete':False})
        with SafeTree(paths.config) as config_tree:
            old_hash = hashlib.sha256(config_tree.read('rclone.conf',limit=65536)).hexdigest() if config_tree.exists('rclone.conf') else None
            config_tree.publish('rclone.conf',credentials,expected=old_hash,mode=0o600,minimum=minimum)
        atomic_json(paths.config/'config.json',config)
        if not reconnect:
            atomic_json(paths.config/'installed.json',{'version':1,'package_id':manifest['package_id'],
                                                       'package_sha256':expected})
        if consume:
            consume_package(archive,identity)
        return {'result':'reconnected' if reconnect else 'installed','photos_imported':imported}


def restore_archives(paths, source, expected, *, minimum=512*1024**2):
    """Explicit import as new Recall archives. Never replace a current document."""
    initialize(paths)
    with lock(paths), SafeTree(source) as tree, tempfile.TemporaryDirectory(dir=paths.state/'staging') as temporary:
        raw = tree.read('manifest.json',limit=4*1024**2)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Restore manifest SHA-256 mismatch')
        manifest = json.loads(raw)
        if (manifest.get('format') != 'toddlerbox-creations' or manifest.get('version') != 1
                or not isinstance(manifest.get('files'),dict) or len(manifest['files']) > 4096):
            raise ValueError('Invalid creation manifest')
        run_id = str(uuid.UUID(manifest['run_id']))
        staged = []
        total = 0
        for name, entry in manifest['files'].items():
            components = parts(name)
            paint = len(components)==2 and components[0]=='paint' and name.endswith('.png')
            typing = (components[0]=='typing' and name.endswith(('.json','.txt')) and
                      (len(components)==2 or len(components)==3 and components[1]=='archive'))
            if not (paint or typing):
                raise ValueError('Unexpected creation path')
            data = tree.read(name)
            total += len(data)
            if total > MAX_TOTAL:
                raise ValueError('Restore exceeds total byte limit')
            if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise ValueError('Restore file checksum mismatch')
            if paint:
                validate_photo(data,name)
                target = 'paint/restored-'+run_id+'-'+components[-1]
            elif name.endswith('.json'):
                typing_text(data)
                target = 'typing/archive/restored-'+run_id+'-'+components[-1]
            else:
                data.decode('utf-8')
                continue  # Authoritative JSON carries styling; text is an export.
            with SafeTree(temporary) as copies:
                copies.publish(target,data,mode=0o600,minimum=minimum)
            staged.append(target)
        imported = 0
        with SafeTree(paths.data) as destination, SafeTree(temporary) as copies:
            for target in staged:
                data = copies.read(target)
                if destination.exists(target):
                    if destination.read(target) != data:
                        raise ValueError('Existing restored archive changed; preserved')
                    continue
                destination.publish(target,data,minimum=minimum)
                imported += 1
        return {'result':'archives-imported','archives_imported':imported}
