from __future__ import annotations

import hashlib
import json
from pathlib import Path
import signal
import tempfile
import time
import uuid

from .ipc import request_save
from .media import typing_text, validate_photo
from .package import config_bytes, credentials_bytes
from .remote import GLOBAL_FAILURES, Rclone, TransferError
from .safeio import MAX_FILE, MAX_TOTAL, SafeTree, atomic_json, digest, parts
from .state import Paths, clock_plausible, initialize, load, lock, now, sweep_staging

UNIT_TIMEOUT = 900  # toddlerbox-sync.service TimeoutStartSec
# Finish, record status and clean staging before systemd's timeout kills the job.
RUN_SECONDS = UNIT_TIMEOUT - 60
# Initial originals are resumable and immutable; they must not starve creations.
INITIAL_SHARE = 0.5
MAX_ISSUE_FILES = 50
# A per-phase byte limit stops that phase only; the run keeps a ceiling across phases.
PHASE_STOP = {'run-byte-limit'}


class Terminated(BaseException):
    """SIGTERM from systemd: record an honest status and let cleanup run."""


def _terminate(_signum, _frame):
    raise Terminated()


def unique_entries(entries):
    result, folded = {}, set()
    for entry in entries:
        path = entry['Path']
        parts(path)
        if path.casefold() in folded:
            raise TransferError('duplicate-cloud-names')
        folded.add(path.casefold())
        result[path] = entry
    return result


def split_duplicates(entries):
    """Drive allows identical names: skip only the colliding photos, keep the rest."""
    groups = {}
    for entry in entries:
        parts(entry['Path'])
        groups.setdefault(entry['Path'].casefold(), []).append(entry)
    unique = {group[0]['Path']: group[0] for group in groups.values() if len(group) == 1}
    duplicates = sorted({entry['Path'] for group in groups.values() if len(group) > 1 for entry in group})
    return unique, duplicates


def same_content(entry, data):
    return (entry and not entry.get('IsDir') and entry.get('Size') == len(data)
            and entry.get('Hashes', {}).get('md5') == hashlib.md5(data).hexdigest())


class Run:
    def __init__(self, paths, *, factory=Rclone, save=request_save, minimum=512*1024**2, seconds=RUN_SECONDS):
        self.paths, self.factory, self.save = paths, factory, save
        self.minimum = minimum
        self.started = time.monotonic()
        self.deadline = self.started + seconds
        self.uuid = initialize(paths)
        previous = load(paths.state/'status.json')
        self.status = {'version':1, 'device_uuid':self.uuid, 'run_id':str(uuid.uuid4()),
                       'state':'running', 'started_at':now(), 'completed_at':None,
                       'last_success':previous.get('last_success'), 'save_current':None,
                       'counts':dict.fromkeys(['photos_downloaded','photos_unchanged','creations_uploaded',
                                              'creations_unchanged','history_preserved','initial_backed_up',
                                              'local_quarantined_skipped'],0),
                       'issues':[], 'issue_count':0, 'issue_files':[]}
        self.total = 0
        self.phase_bytes = 0
        # Any transient snapshot/upload failure withholds the creations manifest.
        self.creations_complete = True
        self.excluded = []

    def issue(self, code, name=None):
        self.status['issue_count'] += 1
        if len(self.status['issues']) < 100:
            self.status['issues'].append(code)
        # Root-only status may name the parent's own files; the shareable report never does.
        if name is not None and len(self.status['issue_files']) < MAX_ISSUE_FILES:
            self.status['issue_files'].append({'issue': code, 'name': name})

    def checkpoint(self):
        atomic_json(self.paths.state/'status.json', self.status)
        if time.monotonic() >= self.deadline:
            raise TransferError('timed-out')

    def budget(self, size):
        self.total += size
        self.phase_bytes += size
        if size > MAX_FILE or self.phase_bytes > MAX_TOTAL or self.total > 2 * MAX_TOTAL:
            raise TransferError('run-byte-limit')
        if time.monotonic() >= self.deadline:
            raise TransferError('timed-out')

    def phase(self, function, *args):
        """One phase's failure is an issue; only global failures stop the later phases."""
        self.phase_bytes = 0
        try:
            function(*args)
        except TransferError as error:
            self.issue(error.code)
            if error.code in GLOBAL_FAILURES:
                raise

    def stage_bytes(self, relative, data):
        self.budget(len(data))
        with SafeTree(self.stage) as tree:
            tree.publish(relative, data, mode=0o600, minimum=self.minimum)
        return self.stage/relative

    def snapshot(self):
        files = {}
        with SafeTree(self.paths.data) as tree:
            for directory in ['paint','typing','typing/archive']:
                try:
                    names = tree.names(directory)
                except FileNotFoundError:
                    continue
                if len(names) > 4096:
                    self.issue('local-file-count-limit')
                    self.creations_complete = False
                    continue
                for name in sorted(names):
                    if name.startswith('.'):
                        continue
                    if directory == 'paint' and not name.lower().endswith('.png'):
                        continue
                    if directory.startswith('typing') and (not name.endswith('.json') or
                            (directory == 'typing' and name not in {'current.json','current-v1.json'})):
                        continue
                    relative = directory+'/'+name
                    if name.startswith('corrupt-'):
                        # Quarantined media stays on the device for the parent; it is not work.
                        self.status['counts']['local_quarantined_skipped'] += 1
                        continue
                    try:
                        # A concurrent atomic app commit may invalidate the first
                        # read. Retry once, never upload a torn in-place write.
                        try:
                            data = tree.read(relative)
                        except ValueError:
                            data = tree.read(relative)
                    except (ValueError, OSError):
                        self.issue('local-snapshot-unavailable', relative)
                        self.creations_complete = False
                        continue
                    try:
                        if directory == 'paint':
                            validate_photo(data, name)
                        else:
                            text = typing_text(data)
                    except (ValueError, TypeError, KeyError):
                        # Deterministic: the same bytes fail every run. Record, do not block.
                        self.issue('local-creation-unsupported', relative)
                        self.excluded.append(relative)
                        continue
                    try:
                        files[relative] = self.stage_bytes('creations/'+relative, data)
                        if directory.startswith('typing'):
                            text_name = relative[:-5]+'.txt'
                            files[text_name] = self.stage_bytes('creations/'+text_name, text)
                    except TransferError as error:
                        if error.code in GLOBAL_FAILURES:
                            raise
                        self.issue(error.code, relative)
                        self.creations_complete = False
        return files

    def put_verified(self, source, remote, *, immutable=False):
        self.remote.put(source, remote, immutable=immutable)
        self.remote.verify(remote, digest(source))

    def initial_backup(self):
        initial = load(self.paths.state/'initial.json')
        if not initial or initial.get('complete'):
            return
        phase_deadline = self.started + INITIAL_SHARE * (self.deadline - self.started)
        verified = initial.get('verified')
        if not isinstance(verified, dict):
            verified = initial['verified'] = {}
        root = self.paths.state/'initial'/initial['package_id']
        destination = 'Initial backup/'+initial['date']
        self.remote.phase_deadline = phase_deadline
        try:
            with SafeTree(root) as originals:
                for name, expected in initial['files'].items():
                    if verified.get(name) == expected['sha256']:
                        continue  # Durable progress from an earlier bounded run.
                    if time.monotonic() >= phase_deadline:
                        raise TransferError('phase-deadline')
                    data = originals.read(name)
                    if hashlib.sha256(data).hexdigest() != expected['sha256']:
                        raise TransferError('initial-original-checksum-mismatch')
                    source = self.stage_bytes('initial/'+name, data)
                    self.put_verified(source, destination+'/'+name, immutable=True)
                    verified[name] = expected['sha256']
                    atomic_json(self.paths.state/'initial.json', initial)
                    self.status['counts']['initial_backed_up'] += 1
                    self.checkpoint()
            manifest = {'format':'toddlerbox-initial-photos','version':1,'files':initial['files']}
            source = self.stage_bytes('initial-manifest.json', json.dumps(manifest,sort_keys=True,indent=2).encode()+b'\n')
            self.put_verified(source, destination+'/manifest.json', immutable=True)
        except TransferError as error:
            if error.code == 'phase-deadline':
                raise TransferError('initial-backup-incomplete') from None
            raise
        finally:
            self.remote.phase_deadline = None
        initial['complete'] = True
        initial['verified_at'] = now()
        atomic_json(self.paths.state/'initial.json', initial)

    def photos(self):
        entries, duplicates = split_duplicates(self.remote.list('Photos'))
        for name in duplicates:
            self.issue('duplicate-cloud-names', name)
        if len(entries) > 4096:
            raise TransferError('photo-count-limit')
        with SafeTree(self.paths.library) as library:
            local_names = {name.casefold():name for name in library.names()}
            for name, entry in sorted(entries.items()):
                if entry.get('IsDir') or '/' in name:
                    self.issue('nested-photos-not-imported', name)
                    continue
                if Path(name).suffix.lower() not in {'.jpg','.jpeg','.png'}:
                    self.issue('unsupported-photo', name)
                    continue
                if type(entry.get('Size')) is not int or not 0 < entry['Size'] <= MAX_FILE:
                    self.issue('photo-size-limit', name)
                    continue
                try:
                    existing_name = local_names.get(name.casefold())
                    current = library.read(existing_name) if existing_name else None
                    if current is not None and same_content(entry, current):
                        self.status['counts']['photos_unchanged'] += 1
                        continue
                    self.budget(entry['Size'])
                    with tempfile.TemporaryDirectory(dir=self.stage) as temporary:
                        download = Path(temporary)/'download'
                        self.remote.get('Photos/'+name, download)
                        data = download.read_bytes()
                        if len(data) != entry['Size'] or (entry.get('Hashes',{}).get('md5') and not same_content(entry,data)):
                            raise TransferError('download-checksum-mismatch')
                        validate_photo(data, name)
                    if existing_name:
                        # Photo names are immutable locally: never race or replace
                        # a parent/child edit, even with valid different cloud bytes.
                        if current != data or existing_name != name:
                            self.issue('local-photo-name-conflict', name)
                            continue
                        self.status['counts']['photos_unchanged'] += 1
                    else:
                        library.publish(name, data, minimum=self.minimum)
                        local_names[name.casefold()] = name
                        self.status['counts']['photos_downloaded'] += 1
                except TransferError as error:
                    if error.code in GLOBAL_FAILURES or error.code in PHASE_STOP:
                        raise
                    self.issue(error.code, name)  # One undownloadable photo never stops the rest.
                except (ValueError, OSError):
                    self.issue('photo-invalid-or-unpublishable', name)
                self.checkpoint()

    def upload_one(self, name, source, entries):
        root = 'Creations/'+self.uuid
        previous = entries.get(name)
        data = source.read_bytes()
        if same_content(previous, data):
            self.status['counts']['creations_unchanged'] += 1
            return
        if previous:
            if previous.get('IsDir') or type(previous.get('Size')) is not int or previous['Size'] > MAX_FILE:
                raise TransferError('unsupported-cloud-creation')
            with tempfile.TemporaryDirectory(dir=self.stage) as temporary:
                old = Path(temporary)/'previous'
                self.remote.get(root+'/'+name, old)
                self.budget(old.stat().st_size)
                old_data = old.read_bytes()
                if not same_content(previous, old_data):
                    raise TransferError('cloud-changed-during-history-copy')
                history = 'History/'+self.uuid+'/'+self.status['run_id']+'/'+name
                self.put_verified(old, history, immutable=True)
                # rclone does not offer a Drive compare-and-swap. Refuse changes
                # observed since listing; concurrent external writers are still a
                # documented provider-level limitation, never silently reconciled.
                current = unique_entries(self.remote.list(root, recursive=True)).get(name)
                if not same_content(current, old_data):
                    raise TransferError('cloud-changed-before-upload')
                self.status['counts']['history_preserved'] += 1
        self.put_verified(source, root+'/'+name)
        self.status['counts']['creations_uploaded'] += 1

    def creations(self, files):
        root = 'Creations/'+self.uuid
        entries = unique_entries(self.remote.list(root, recursive=True))
        manifest = {'format':'toddlerbox-creations','version':1,'device_uuid':self.uuid,
                    'run_id':self.status['run_id'],'created_at':self.status['started_at'],
                    'files':{name:{'size':path.stat().st_size,'sha256':digest(path)} for name,path in files.items()}}
        for name, source in sorted(files.items()):
            try:
                self.upload_one(name, source, entries)
            except TransferError as error:
                if error.code in GLOBAL_FAILURES or error.code in PHASE_STOP:
                    self.creations_complete = False
                    raise
                self.issue(error.code, name)
                self.creations_complete = False
            self.checkpoint()
        if not self.creations_complete:
            # The previous complete manifest stays; restores verify every file
            # against it and refuse a mixture rather than restore partial state.
            self.issue('creations-manifest-withheld')
            return
        if self.excluded:
            manifest['excluded'] = sorted(self.excluded)
        # Manifest is last. Explicit restores verify it and refuse partial states.
        source = self.stage_bytes('creations/manifest.json', json.dumps(manifest,sort_keys=True,indent=2).encode()+b'\n')
        self.upload_one('manifest.json', source, entries)

    def execute(self):
        self.checkpoint()
        try:
            if not (self.paths.config/'installed.json').exists():
                self.status['state'] = 'unconfigured'
                return self.status
            if not clock_plausible():
                raise TransferError('clock-or-certificate')
            with SafeTree(self.paths.config) as config_tree:
                config = config_bytes(config_tree.read('config.json',limit=65536))
                credentials_bytes(config_tree.read('rclone.conf',limit=65536),config['root_folder_id'])
            self.status['save_current'] = self.save()
            if self.status['save_current'] != 'ok':
                self.issue('save-current-'+self.status['save_current'])
            with tempfile.TemporaryDirectory(prefix='run-',dir=self.paths.state/'staging') as temporary:
                self.stage = Path(temporary)
                files = self.snapshot()
                self.remote = self.factory(self.paths,config['root_folder_id'],self.stage,
                                           deadline=self.deadline,minimum=self.minimum)
                # Child work is the precious direction: it is never queued behind downloads.
                self.phase(self.initial_backup)
                self.phase(self.creations, files)
                self.phase(self.photos)
            self.status['state'] = 'partial' if self.status['issue_count'] else 'success'
        except TransferError as error:
            if self.status['issues'][-1:] != [error.code]:
                self.issue(error.code)  # Raised outside a phase (start or snapshot).
            self.status['state'] = 'timed_out' if error.code == 'timed-out' else 'partial'
        except Terminated:
            self.issue('job-interrupted')
            self.status['state'] = 'interrupted'
            raise
        except (OSError,ValueError,KeyError,TypeError):
            self.issue('local-configuration-or-storage-failure')
            self.status['state'] = 'failed'
        finally:
            self.status['completed_at'] = now()
            if self.status['state'] == 'success':
                self.status['last_success'] = {'at':self.status['completed_at'],
                                              'run_id':self.status['run_id'],'counts':dict(self.status['counts'])}
            atomic_json(self.paths.state/'status.json',self.status)
        return self.status


def main():
    paths = Paths()
    signal.signal(signal.SIGTERM, _terminate)
    initialize(paths)
    with lock(paths):
        # A killed job or import cannot clean up after itself; nothing else is running now.
        sweep_staging(paths)
        try:
            Run(paths).execute()
        except Terminated:
            raise SystemExit(143) from None


if __name__ == '__main__':
    main()
