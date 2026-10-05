#!/usr/bin/env python3
"""Download the public installer anonymously and verify it before publication.

Run without sudo: python3 scripts/download-installer.py /chosen/path/ToddlerBox.iso
The initial installer trusts GitHub HTTPS; installed updates additionally verify
Ed25519 signatures against the key embedded in that installer.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.parse
import urllib.request

SOURCE = 'https://raw.githubusercontent.com/famulare/ToddlerBox/main/docs/releases/installer-0de59fe202491fa9.json'
HOSTS = {'raw.githubusercontent.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}


def check_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in HOSTS or parts.username or parts.password or parts.port not in {None, 443}:
        raise ValueError('Unsupported installer destination')


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    check_url(url)
    return urllib.request.build_opener(Redirects()).open(urllib.request.Request(url, headers={'User-Agent': 'ToddlerBox-installer/1'}), timeout=60)


def download(output):
    with fetch(SOURCE) as response:
        check_url(response.geturl())
        data = response.read(65537)
    if len(data) > 65536:
        raise ValueError('Oversized installer metadata')
    value = json.loads(data)
    iso = value['iso']
    if (value.get('status') or value.get('architecture') != 'amd64'
            or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', value['release_tag'])
            or iso['filename'] != 'toddlerbox-installer.iso'
            or type(iso['bytes']) is not int or not 0 < iso['bytes'] <= 4 * 1024**3
            or not re.fullmatch(r'[0-9a-f]{64}', iso['sha256'])):
        raise ValueError('Unsupported or unqualified installer metadata')
    output = Path(output)
    if output.is_symlink():
        raise ValueError('Existing symlink preserved')
    if output.exists():
        with output.open('rb') as handle:
            digest = hashlib.sha256()
            while data := handle.read(1024 * 1024):
                digest.update(data)
            if output.stat().st_size == iso['bytes'] and digest.hexdigest() == iso['sha256']:
                print('Existing installer verified:', output)
                return
        raise ValueError('Different existing file preserved')
    url = f"https://github.com/famulare/ToddlerBox/releases/download/{value['release_tag']}/{iso['filename']}"
    with tempfile.TemporaryDirectory(prefix='.toddlerbox-download-', dir=output.parent) as temporary:
        path = Path(temporary) / 'installer'
        total = 0
        digest = hashlib.sha256()
        started = time.monotonic()
        with fetch(url) as response, path.open('xb') as handle:
            check_url(response.geturl())
            while data := response.read(1024 * 1024):
                total += len(data)
                if total > iso['bytes'] or time.monotonic() - started > 1800:
                    raise ValueError('Installer download exceeded limits')
                digest.update(data)
                handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if total != iso['bytes'] or digest.hexdigest() != iso['sha256']:
            raise ValueError('Incomplete or corrupt installer; destination preserved')
        os.link(path, output, follow_symlinks=False)
        fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    print('Installer verified:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    download(parser.parse_args().output)
