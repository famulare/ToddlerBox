"""Explicit parent USB setup: transfer integrity, not authenticated provenance."""
from dataclasses import dataclass
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from .install import setup
from .safeio import MAX_TOTAL, SafeTree, atomic_json, parts, reserve
from .state import Paths, initialize, now


class Refused(ValueError):
    pass


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@dataclass(frozen=True)
class Candidate:
    mount: Path
    name: str
    size: int
    file_identity: tuple
    mount_identity: tuple


def usb_mounts():
    result = subprocess.run(['/usr/bin/lsblk', '--json', '--output', 'TRAN,RM,MOUNTPOINTS'],
                            check=True, capture_output=True, text=True, timeout=5)
    mounts = set()
    def walk(device, removable=False):
        removable = removable or device.get('tran') == 'usb' or device.get('rm') is True
        if removable:
            for path in device.get('mountpoints') or []:
                if isinstance(path, str) and path.startswith(('/media/', '/run/media/')):
                    mounts.add(Path(path))
        for child in device.get('children') or []:
            walk(child, removable)
    for device in json.loads(result.stdout)['blockdevices']:
        walk(device)
    return sorted(mounts)


def discover(mounts=None):
    """Only mounted removable/USB roots, only on explicit setup, no recursion."""
    candidates = []
    for mount in usb_mounts() if mounts is None else mounts:
        try:
            with SafeTree(mount) as tree:
                device = os.fstat(tree.fd)
                for name in sorted(tree.names()):
                    if not (name.endswith('.toddlerbox-setup.tar.gz') or
                            re.fullmatch(r'toddlerbox-setup-\d{4}-\d{2}-\d{2}\.tar\.gz', name)):
                        continue
                    parts(name)  # Also excludes terminal-control characters.
                    info = os.stat(name, dir_fd=tree.fd, follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= MAX_TOTAL + 16*1024**2:
                        candidates.append(Candidate(Path(mount), name, info.st_size,
                                                    identity(info), (device.st_dev, device.st_ino)))
        except (OSError, ValueError):
            continue  # A removed or unsafe volume is not a candidate.
    return candidates


def checksum(raw, filename):
    try:
        text = raw.decode('utf-8').strip()
    except UnicodeError:
        raise Refused('Checksum is not plain UTF-8 text. Recopy the Mac checksum file.') from None
    match = re.fullmatch(r'([0-9a-fA-F]{64})(?:[ \t]+\*?([^\r\n]+))?', text)
    if not match or (match[2] is not None and match[2] != filename):
        raise Refused('Checksum is invalid, ambiguous, or names another file. Recopy the matching Mac checksum file.')
    return match[1].lower()


@contextmanager
def parent_install():
    from appliance import guard, maintenance_lock
    with maintenance_lock():
        try:
            guard()  # Recheck after prompts/copy; controller uses this lock too.
        except ValueError:
            raise Refused('Return to authenticated parent mode and finish other maintenance, then retry setup.') from None
        yield


def snapshot(candidate, directory, *, minimum=512*1024**2):
    """Verify a stable private copy, never import changing removable bytes."""
    target = Path(directory) / 'verified.tar.gz'
    with SafeTree(candidate.mount) as tree:
        mount = os.fstat(tree.fd)
        if (mount.st_dev, mount.st_ino) != candidate.mount_identity:
            raise Refused('USB changed or was removed. Remount it and retry setup.')
        sidecar = tree.read(candidate.name + '.sha256', limit=4096)
        expected = checksum(sidecar, candidate.name)
        with tree.parent(candidate.name) as (fd, name):
            source = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(source, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    identity(info) != candidate.file_identity):
                raise Refused('Package changed since selection. Recopy it and retry setup.')
            digest = hashlib.sha256()
            with target.open('xb') as copy:
                os.fchmod(copy.fileno(), 0o600)
                reserve(copy.fileno(), candidate.size, minimum)
                remaining = candidate.size
                while remaining:
                    data = stream.read(min(1024**2, remaining))
                    if not data:
                        raise Refused('USB copy was interrupted. Recopy the package and checksum.')
                    copy.write(data)
                    digest.update(data)
                    remaining -= len(data)
                copy.flush()
                os.fsync(copy.fileno())
            current = os.stat(candidate.name, dir_fd=tree.fd, follow_symlinks=False)
            if (identity(os.fstat(stream.fileno())) != candidate.file_identity or
                    identity(current) != candidate.file_identity or current.st_nlink != 1 or
                    tree.read(candidate.name + '.sha256', limit=4096) != sidecar):
                raise Refused('USB files changed during verification. Recopy both files and retry.')
            with SafeTree(candidate.mount) as mounted:
                current_mount = os.fstat(mounted.fd)
                if (current_mount.st_dev, current_mount.st_ino) != candidate.mount_identity:
                    raise Refused('USB changed or was removed. Remount it and retry setup.')
            if digest.hexdigest() != expected:
                raise Refused('Full SHA-256 does not match. Recopy both files from your Mac; do not install this copy.')
    return target, expected


def flow(paths, *, find=discover, ask=input, tell=print, minimum=512*1024**2):
    candidates = find()
    if not candidates:
        raise Refused('No setup package found. Mount the USB in Files and place the package plus .sha256 at its root, then retry.')
    for number, item in enumerate(candidates, 1):
        # JSON quoting prevents a volume label injecting terminal controls.
        tell(f'{number}. USB {json.dumps(item.mount.name)}: {json.dumps(item.name)} ({item.size:,} bytes)')
    if len(candidates) == 1:
        selected = 0
    else:
        choice = ask('Choose a package number (Enter cancels): ').strip()
        if not choice:
            tell('Cancelled. Nothing installed.')
            return None
        if not choice.isascii() or not choice.isdecimal() or not 1 <= int(choice) <= len(candidates):
            raise Refused('Invalid selection. Retry and choose one of the listed package numbers.')
        selected = int(choice) - 1
    tell('The adjacent checksum verifies transfer integrity, not who made the files.')
    if ask('Install the private package you prepared on your Mac from this USB? [y/N] ').strip().lower() != 'y':
        tell('Cancelled. Nothing installed.')
        return None
    initialize(paths)
    with tempfile.TemporaryDirectory(prefix='usb-', dir=paths.state / 'staging') as temporary:
        archive, expected = snapshot(candidates[selected], temporary, minimum=minimum)
        tell(f'Full SHA-256 verified: {expected}')
        with parent_install():
            result = setup(paths, archive, expected, minimum=minimum)  # Never consume transfer originals.
            atomic_json(paths.state / 'setup-receipt.json', {'version':1, 'at':now(),
                        'package_sha256':expected, **result})
    if result['result'] == 'already-installed':
        tell('Already installed. 0 new photos imported; existing work and credentials preserved.')
    else:
        tell(f"Success. {result['photos_imported']} new photos imported. USB files and existing child work preserved.")
    return result


def main(paths=None):
    result = 0
    try:
        from appliance import guard
        try:
            guard()
        except ValueError:
            raise Refused('Return to authenticated parent mode and finish other maintenance, then retry setup.') from None
        flow(paths or Paths())
    except Refused as error:
        result = 1
        print(str(error))  # Only fixed public messages; never echo parser/provider errors.
    except BlockingIOError:
        result = 2
        print('A sync/import is running. Wait for it to finish, then retry setup.')
    except OSError as error:
        result = 1
        print('Not enough free space. Free space in parent mode, then retry; existing work is preserved.'
              if error.errno == errno.ENOSPC else
              'USB/file access failed. Remount the USB and recopy both files, then retry. Existing work is preserved.')
    except (ValueError, KeyError, TypeError, subprocess.SubprocessError):
        result = 1
        print('Import refused or incomplete. Check the Mac package and photo-name conflicts; use Sync Status, then retry. Existing work is preserved.')
    finally:
        try:
            input('Press Enter to close.')
        except EOFError:
            pass
    return result
