"""Strict private package reader. No extractall, links, or executable settings."""
from __future__ import annotations

import configparser
import datetime as dt
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import uuid

from .media import validate_photo
from .safeio import MAX_FILE, MAX_TOTAL, SafeTree, parts

MAX_PHOTOS = 4096


def config_bytes(data):
    value = json.loads(data)
    if (not isinstance(value, dict) or set(value) != {'version', 'root_folder_id'}
            or type(value['version']) is not int or value['version'] != 1
            or not isinstance(value['root_folder_id'], str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{10,128}', value['root_folder_id'])):
        raise ValueError('Invalid sync configuration')
    return value


def credentials_bytes(data, root_id):
    if len(data) > 65536:
        raise ValueError('Credentials too large')
    config = configparser.ConfigParser(interpolation=None, strict=True)
    config.read_string(data.decode('utf-8'))
    keys = {'type', 'client_id', 'client_secret', 'scope', 'token', 'root_folder_id'}
    if config.defaults() or config.sections() != ['toddlerbox'] or set(config['toddlerbox']) != keys:
        raise ValueError('Only the fixed toddlerbox Drive remote is allowed')
    value = dict(config['toddlerbox'])
    if value['type'] != 'drive' or value['root_folder_id'] != root_id:
        raise ValueError('Drive root mismatch')
    if value['scope'].replace(' ', '') != 'drive.readonly,drive.file':
        raise ValueError('Expected drive.readonly,drive.file scopes')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{5,240}\.apps\.googleusercontent\.com', value['client_id']):
        raise ValueError('Own Desktop OAuth client is required')
    if not re.fullmatch(r'[A-Za-z0-9_./+-]{8,256}', value['client_secret']):
        raise ValueError('Invalid client secret field')
    token = json.loads(value['token'])
    if (not isinstance(token, dict) or set(token) - {'access_token','token_type','refresh_token','expiry','expires_in'}
            or token.get('token_type', '').lower() != 'bearer'):
        raise ValueError('Invalid OAuth token')
    for key in ('access_token', 'refresh_token'):
        item = token.get(key)
        if not isinstance(item, str) or not 8 <= len(item) <= 8192 or any(ord(c) < 33 for c in item):
            raise ValueError('Missing OAuth token field')
    dt.datetime.fromisoformat(token['expiry'].replace('Z', '+00:00'))
    config['toddlerbox']['scope'] = 'drive.readonly,drive.file'
    output = io.StringIO()
    config.write(output)
    return output.getvalue().encode()


def manifest_bytes(data, actual):
    if len(data) > 4*1024**2:
        raise ValueError('Manifest too large')
    value = json.loads(data)
    if (not isinstance(value, dict) or set(value) != {'format','version','package_id','created_at','files'}
            or value['format'] != 'toddlerbox-setup' or type(value['version']) is not int
            or value['version'] != 1 or str(uuid.UUID(value['package_id'])) != value['package_id']):
        raise ValueError('Unsupported setup package')
    date = dt.datetime.strptime(value['created_at'], '%Y-%m-%dT%H:%M:%SZ')
    if not 2020 <= date.year <= 2100 or value['files'] != actual:
        raise ValueError('Manifest membership, size or SHA-256 mismatch')
    return value


def inspect_package(path, expected, stage, *, minimum=512*1024**2):
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('Provide the independently checked archive SHA-256')
    path, stage = Path(path).absolute(), Path(stage)
    with SafeTree(path.parent) as source_tree, source_tree.parent(path.name) as (fd, name):
        source = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd)
    with os.fdopen(source, 'rb') as raw:
        before = os.fstat(raw.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_TOTAL + 16*1024**2:
            raise ValueError('Invalid package file')
        if hashlib.file_digest(raw, 'sha256').hexdigest() != expected:
            raise ValueError('Archive SHA-256 mismatch')
        raw.seek(0)
        actual, seen, total = {}, set(), 0
        manifest = None
        # Read only ordinary USTAR file headers. Reject PAX/GNU extension records
        # before tarfile can allocate buffers from their attacker-supplied lengths.
        with gzip.GzipFile(fileobj=raw, mode='rb') as archive, SafeTree(stage) as destination:
            while True:
                block = archive.read(512)
                if block == b'\0' * 512:
                    tail = archive.read(65536)
                    if len(tail) == 65536 or any(tail):
                        raise ValueError('Invalid archive trailer')
                    break
                if len(block) != 512:
                    raise ValueError('Truncated tar header')
                info = tarfile.TarInfo.frombuf(block, 'utf-8', 'strict')
                name = info.name
                components = parts(name)
                if (not info.isreg() or info.linkname or name.casefold() in seen
                        or len(seen) >= MAX_PHOTOS+3 or info.size < 0):
                    raise ValueError('Invalid, linked or duplicate archive member')
                seen.add(name.casefold())
                is_photo = len(components) == 3 and components[:2] == ['photos','library']
                if name not in {'manifest.json','config.json','rclone.conf'} and not is_photo:
                    raise ValueError('Only flat original photo imports are accepted')
                limit = MAX_FILE if is_photo else 4*1024**2 if name == 'manifest.json' else 65536
                total += info.size
                if info.size > limit or total > MAX_TOTAL:
                    raise ValueError('Package limits exceeded')
                data = archive.read(info.size)
                padding = archive.read((-info.size) % 512)
                if len(data) != info.size or len(padding) != (-info.size) % 512 or any(padding):
                    raise ValueError('Truncated or invalid tar payload')
                if is_photo:
                    validate_photo(data, name)
                if name == 'manifest.json':
                    manifest = data
                else:
                    actual[name] = {'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
                destination.publish(name, data, mode=0o600, minimum=minimum)
        after = os.fstat(raw.fileno())
        if (before.st_size,before.st_mtime_ns,before.st_ctime_ns) != (after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise ValueError('Package changed during verification')
    if manifest is None or not {'config.json','rclone.conf'} <= set(actual):
        raise ValueError('Missing package configuration')
    metadata = manifest_bytes(manifest, actual)
    config = config_bytes((stage/'config.json').read_bytes())
    credentials_bytes((stage/'rclone.conf').read_bytes(), config['root_folder_id'])
    return metadata, config, (before.st_dev,before.st_ino,before.st_mtime_ns,before.st_size)


def consume_package(path, identity):
    """Remove only the same verified transfer file, after successful installation."""
    path = Path(path).absolute()
    with SafeTree(path.parent) as tree, tree.parent(path.name) as (fd, name):
        now = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if (now.st_dev,now.st_ino,now.st_mtime_ns,now.st_size) != identity or now.st_nlink != 1:
            raise ValueError('Transfer file changed; not removed')
        os.unlink(name, dir_fd=fd)
        os.fsync(fd)
