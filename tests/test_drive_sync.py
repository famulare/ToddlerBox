import hashlib
import io
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import tarfile
import time
from types import SimpleNamespace

import pytest
from PIL import Image, ImageFile

sys.path.insert(0,str(Path(__file__).parents[1]))
from sync_fixtures import CONFIG,CREDENTIALS,MemoryDrive,large_jpeg,large_png,package,paths,png,typing
from system.tbx_sync import cli
from system.tbx_sync.install import setup,restore_archives
from system.tbx_sync.media import validate_photo
from system.tbx_sync.package import inspect_package,credentials_bytes
from system.tbx_sync.remote import TransferError,Rclone
from system.tbx_sync.safeio import SafeTree,digest,atomic_json
from system.tbx_sync.state import initialize,load,lock,finalize
from system.tbx_sync.worker import Run
from toddlerbox.photos.app import _decode_photo,_prepare_thumbnail
from toddlerbox.runtime.control import AppChannel,draw_receipt
from toddlerbox.ui import theme
import pygame


def installed(tmp_path):
    locations=paths(tmp_path/'device')
    archive,checksum=package(tmp_path)
    setup(locations,archive,checksum,minimum=0)
    return locations


def test_setup_verified_repeat_preserves_newer_files_credentials_uuid_and_work(tmp_path):
    locations=paths(tmp_path/'device')
    archive,checksum=package(tmp_path)
    (locations.data/'typing/current.json').write_bytes(typing('newer work'))
    result=setup(locations,archive,checksum,minimum=0)
    identity=load(locations.state/'device.json')
    assert result['photos_imported']==1
    assert (locations.library/'example.png').read_bytes()==png()
    (locations.library/'example.png').write_bytes(png('purple'))
    refreshed=CREDENTIALS.replace(b'synthetic-not-a-real-access-token',b'refreshed-synthetic-token')
    (locations.config/'rclone.conf').write_bytes(refreshed)
    assert setup(locations,archive,checksum,minimum=0)['result']=='already-installed'
    assert load(locations.state/'device.json')==identity
    assert (locations.library/'example.png').read_bytes()==png('purple')
    assert (locations.config/'rclone.conf').read_bytes()==refreshed
    assert (locations.data/'typing/current.json').read_bytes()==typing('newer work')
    assert stat.S_IMODE((locations.config/'rclone.conf').stat().st_mode)==0o600


def test_bad_package_never_consumed_or_publishes_partial_data(tmp_path):
    locations=paths(tmp_path/'device')
    archive,checksum=package(tmp_path,mutate=lambda entries:entries+[('../outside',b'no')])
    with pytest.raises(ValueError):setup(locations,archive,checksum,consume=True,minimum=0)
    assert archive.exists()
    assert not list(locations.library.iterdir())
    assert not (locations.config/'installed.json').exists()


@pytest.mark.parametrize('kind',[tarfile.SYMTYPE,tarfile.LNKTYPE,tarfile.DIRTYPE,tarfile.FIFOTYPE,tarfile.XHDTYPE])
def test_links_special_files_and_extended_headers_are_refused(tmp_path,kind):
    def attack(entries):
        info=tarfile.TarInfo('photos/library/attack.jpg');info.type=kind
        if kind in {tarfile.SYMTYPE,tarfile.LNKTYPE}:info.linkname='/etc/shadow'
        return entries+[(info,b'')]
    archive,checksum=package(tmp_path,mutate=attack)
    stage=tmp_path/'stage';stage.mkdir()
    with pytest.raises((ValueError,tarfile.HeaderError)):inspect_package(archive,checksum,stage,minimum=0)


@pytest.mark.parametrize('name',['photos/library/nested/image.png','photos/library/../image.png','photos/library/EXAMPLE.png'])
def test_nested_traversal_and_case_colliding_photos_are_refused(tmp_path,name):
    archive,checksum=package(tmp_path,mutate=lambda entries:entries+[(name,png())])
    stage=tmp_path/'stage';stage.mkdir()
    with pytest.raises(ValueError):inspect_package(archive,checksum,stage,minimum=0)


def test_hash_mismatch_and_existing_name_conflict_preserve_everything(tmp_path):
    locations=paths(tmp_path/'device')
    archive,checksum=package(tmp_path,photos={'a.png':png(),'z.png':png('green')})
    with pytest.raises(ValueError):setup(locations,archive,'0'*64,minimum=0)
    (locations.library/'z.png').write_bytes(png('blue'))
    with pytest.raises(ValueError):setup(locations,archive,checksum,minimum=0)
    assert not (locations.library/'a.png').exists()
    assert (locations.library/'z.png').read_bytes()==png('blue')
    assert archive.exists()


def test_consumption_only_after_complete_install(tmp_path):
    locations=paths(tmp_path/'device');archive,checksum=package(tmp_path)
    setup(locations,archive,checksum,consume=True,minimum=0)
    assert not archive.exists()
    assert (locations.config/'installed.json').exists()
    assert not list((locations.state/'staging').iterdir())


def test_reconnect_preserves_identity_photos_and_child_work(tmp_path):
    locations=installed(tmp_path);identity=load(locations.state/'device.json')
    (locations.data/'paint/latest.png').write_bytes(png('purple'))
    archive,checksum=package(tmp_path,files={'config.json':CONFIG,'rclone.conf':CREDENTIALS.replace(b'synthetic-not-a-real-access-token',b'reconnected-synthetic-token')})
    setup(locations,archive,checksum,reconnect=True,minimum=0)
    assert b'reconnected-synthetic-token' in (locations.config/'rclone.conf').read_bytes()
    assert load(locations.state/'device.json')==identity
    assert (locations.data/'paint/latest.png').read_bytes()==png('purple')
    assert (locations.library/'example.png').read_bytes()==png()


@pytest.mark.parametrize('extra',['auth_url = https://evil.invalid\n','service_account_file = /etc/shadow\n','[other]\ntype = local\n'])
def test_credential_config_cannot_redirect_or_add_readers(extra):
    with pytest.raises(ValueError):credentials_bytes(CREDENTIALS+extra.encode(),'synthetic_root_1234567890')


def test_private_read_rejects_symlinks_hardlinks_and_symlinked_ancestors(tmp_path):
    root=tmp_path/'data';root.mkdir();private=tmp_path/'private';private.write_text('private')
    (root/'symlink').symlink_to(private)
    os.link(private,root/'hardlink')
    (root/'directory').symlink_to(tmp_path,target_is_directory=True)
    with SafeTree(root) as tree:
        for name in ['symlink','hardlink','directory/private']:
            with pytest.raises((ValueError,OSError)):tree.read(name)
    alias=tmp_path/'alias';alias.symlink_to(root,target_is_directory=True)
    with pytest.raises(OSError):SafeTree(alias)


def test_photo_publication_refuses_racing_destination_and_preserves_old_file(tmp_path):
    with SafeTree(tmp_path) as tree:
        tree.publish('photo.png',png(),minimum=0)
        with pytest.raises(FileExistsError):tree.publish('photo.png',png('blue'),minimum=0)
        assert tree.read('photo.png')==png()
        with pytest.raises(ValueError):tree.publish('photo.png',png('blue'),expected='0'*64,minimum=0)
        assert tree.read('photo.png')==png()
    assert not list(tmp_path.glob('.toddlerbox-*'))


def test_snapshot_is_immutable_after_later_app_commit_and_text_export_is_authoritative(tmp_path):
    locations=installed(tmp_path);drive=MemoryDrive()
    current=locations.data/'typing/current.json';current.write_bytes(typing('before'))
    (locations.data/'paint/latest.png').write_bytes(png())
    def race(source,remote):current.write_bytes(typing('after'))
    drive.before_put=race
    result=Run(locations,factory=drive,save=lambda:'ok',minimum=0).execute()
    assert result['state']=='success'
    root='Creations/'+result['device_uuid']
    assert drive.files[root+'/typing/current.json']==typing('before')
    assert drive.files[root+'/typing/current.txt']==b'before\n'
    assert current.read_bytes()==typing('after')
    assert drive.files['Initial backup/2026-10-03/example.png']==png()
    assert result['last_success']['run_id']==result['run_id']


def test_failed_save_uses_last_durable_work_and_marks_partial(tmp_path):
    locations=installed(tmp_path);drive=MemoryDrive()
    (locations.data/'typing/current.json').write_bytes(typing('durable'))
    result=Run(locations,factory=drive,save=lambda:'timeout',minimum=0).execute()
    assert result['state']=='partial'
    assert result['last_success'] is None
    assert 'save-current-timeout' in result['issues']
    assert drive.files['Creations/'+result['device_uuid']+'/typing/current.txt']==b'durable\n'


def test_history_is_verified_before_changed_cloud_creation_and_never_deleted(tmp_path):
    locations=installed(tmp_path);drive=MemoryDrive()
    current=locations.data/'paint/latest.png';current.write_bytes(png())
    first=Run(locations,factory=drive,save=lambda:'ok',minimum=0).execute()
    root='Creations/'+first['device_uuid']
    current.write_bytes(png('blue'))
    second=Run(locations,factory=drive,save=lambda:'ok',minimum=0).execute()
    history='History/'+first['device_uuid']+'/'+second['run_id']+'/paint/latest.png'
    assert drive.files[history]==png()
    assert drive.files[root+'/paint/latest.png']==png('blue')
    history_check=next(i for i,op in enumerate(drive.operations) if op==('verify',history))
    replacement=next(i for i,op in enumerate(drive.operations) if op[0:2]==('put',root+'/paint/latest.png') and op[2]==png('blue'))
    assert history_check<replacement
    current.unlink()
    third=Run(locations,factory=drive,save=lambda:'ok',minimum=0).execute()
    assert third['state']=='success'
    assert drive.files[root+'/paint/latest.png']==png('blue')
    assert drive.files[history]==png()
    assert {op[0] for op in drive.operations}<={'get','put','verify'}


def test_failed_history_verification_does_not_overwrite_cloud(tmp_path):
    locations=installed(tmp_path);drive=MemoryDrive()
    current=locations.data/'paint/latest.png';current.write_bytes(png())
    first=Run(locations,factory=drive,save=lambda:'ok',minimum=0).execute()
    verify=drive.verify
    def fail_history(remote,expected):
        if remote.startswith('History/'):raise TransferError('remote-checksum-mismatch')
        verify(remote,expected)
    drive.verify=fail_history
    current.write_bytes(png('blue'))
    second=Run(locations,factory=drive,save=lambda:'ok',minimum=0).execute()
    assert second['state']=='partial'
    assert drive.files['Creations/'+first['device_uuid']+'/paint/latest.png']==png()
    assert second['last_success']==first['last_success']


def test_photos_copy_only_no_clobber_nested_or_invalid_publication(tmp_path):
    locations=installed(tmp_path);drive=MemoryDrive()
    drive.files.update({'Photos/new.png':png('blue'),'Photos/example.png':png('purple'),
                        'Photos/nested/no.png':png(),'Photos/bad.png':b'not an image'})
    result=Run(locations,factory=drive,save=lambda:'ok',minimum=0).execute()
    assert result['state']=='partial'
    assert result['counts']['photos_downloaded']==1
    assert (locations.library/'new.png').read_bytes()==png('blue')
    assert (locations.library/'example.png').read_bytes()==png()
    assert not (locations.library/'bad.png').exists()
    assert not (locations.library/'no.png').exists()
    assert not any(op[0]=='put' and op[1].startswith('Photos/') for op in drive.operations)


@pytest.mark.parametrize('reason',['offline-or-unreachable','authorization-required','timed-out'])
def test_remote_failure_preserves_last_success_and_reports_reason(tmp_path,reason):
    locations=installed(tmp_path);drive=MemoryDrive()
    first=Run(locations,factory=drive,save=lambda:'ok',minimum=0).execute()
    drive.fail=TransferError(reason)
    result=Run(locations,factory=drive,save=lambda:'ok',minimum=0).execute()
    assert result['state']==('timed_out' if reason=='timed-out' else 'partial')
    assert result['last_success']==first['last_success']
    assert reason in result['issues']


def test_unconfigured_job_makes_no_remote_or_save_request(tmp_path):
    locations=paths(tmp_path)
    def prohibited(*args,**kwargs):pytest.fail('Unexpected transfer or save request')
    result=Run(locations,factory=prohibited,save=prohibited,minimum=0).execute()
    assert result['state']=='unconfigured'


def test_disk_reserve_refuses_download_publication_and_leaves_originals(tmp_path,monkeypatch):
    locations=installed(tmp_path);drive=MemoryDrive()
    def no_space(*args,**kwargs):raise OSError(28,'synthetic ENOSPC')
    # Refuse data/staging publication while still permitting small status records.
    from system.tbx_sync import safeio
    real=safeio.reserve
    monkeypatch.setattr(safeio,'reserve',lambda fd,additional=0,minimum=0: no_space() if minimum else real(fd,additional,minimum))
    result=Run(locations,factory=drive,save=lambda:'ok',minimum=512).execute()
    assert result['state']=='failed'
    assert (locations.library/'example.png').read_bytes()==png()
    assert not drive.operations


def test_lock_excludes_second_job_and_kill_timeout_status_is_truthful(tmp_path,monkeypatch):
    locations=paths(tmp_path);initialize(locations)
    with lock(locations):
        with pytest.raises(BlockingIOError):
            with lock(locations):pass
    atomic_json(locations.state/'status.json',{'state':'running','last_success':{'at':'earlier'},'issues':[]})
    finalize(locations,'timeout')
    assert load(locations.state/'status.json')['state']=='timed_out'
    atomic_json(locations.state/'status.json',{'state':'running','last_success':{'at':'earlier'}})
    monkeypatch.setattr(cli,'service_state',lambda:{'ActiveState':'failed','Result':'signal'})
    result=cli.status(locations)
    assert result['state']=='interrupted' and result['last_success']=={'at':'earlier'}


def test_explicit_restore_imports_recall_archives_never_current_work(tmp_path):
    locations=installed(tmp_path);drive=MemoryDrive()
    current=locations.data/'typing/current.json';current.write_bytes(typing('earlier'))
    result=Run(locations,factory=drive,save=lambda:'ok',minimum=0).execute()
    source=tmp_path/'restore';source.mkdir()
    root='Creations/'+result['device_uuid']+'/'
    for name,data in drive.files.items():
        if name.startswith(root):
            destination=source/name[len(root):];destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
    current.write_bytes(typing('newer'))
    checksum=digest(source/'manifest.json')
    assert restore_archives(locations,source,checksum,minimum=0)['archives_imported']==1
    assert restore_archives(locations,source,checksum,minimum=0)['archives_imported']==0
    assert current.read_bytes()==typing('newer')
    assert next((locations.data/'typing/archive').glob('*.json')).read_bytes()==typing('earlier')


def test_large_original_jpeg_downsamples_before_decode_for_thumbnail_main_and_import(tmp_path,monkeypatch):
    original=large_jpeg();path=tmp_path/'large.jpg';path.write_bytes(original)
    decoded=[];real=ImageFile.ImageFile.load
    def bounded(image,*args,**kwargs):
        decoded.append(image.size)
        assert image.width*image.height<=40_000_000
        return real(image,*args,**kwargs)
    monkeypatch.setattr(ImageFile.ImageFile,'load',bounded)
    thumb=_prepare_thumbnail(path,tmp_path/'thumb.png',(320,240))
    main=_decode_photo(path,(1366,768),upscale=True)
    validate_photo(original,'large.jpg')
    assert thumb[1][0]<=320 and thumb[1][1]<=240
    assert main[1][0]<=1366 and main[1][1]<=768
    assert decoded and max(w*h for w,h in decoded)<13_000_000
    assert decoded[0][0]*decoded[0][1]<1_000_000
    assert path.read_bytes()==original
    with pytest.raises(ValueError,match='40000000'):_decode_photo(path)


def test_large_png_and_excessive_jpeg_headers_are_refused_before_decode(tmp_path,monkeypatch):
    path=tmp_path/'large.png';path.write_bytes(large_png())
    monkeypatch.setattr(ImageFile.ImageFile,'load',lambda *a,**k:pytest.fail('Full image allocation attempted'))
    with pytest.raises(ValueError,match='40000000'):_decode_photo(path,(320,240))
    with pytest.raises(ValueError,match='40000000'):validate_photo(path.read_bytes(),path.name)
    huge=tmp_path/'header.jpg';huge.write_bytes(large_jpeg(10000,8001))
    with pytest.raises(ValueError,match='absolute header'):_decode_photo(huge,(320,240))


def test_initial_backup_matches_mac_flat_manifest_and_large_original_import(tmp_path):
    original=large_jpeg()
    locations=paths(tmp_path/'device')
    archive,checksum=package(tmp_path,photos={'original.jpg':original})
    setup(locations,archive,checksum,minimum=0)
    assert (locations.library/'original.jpg').read_bytes()==original
    records={'original.jpg':{'size':len(original),'sha256':hashlib.sha256(original).hexdigest()}}
    raw=(json.dumps({'format':'toddlerbox-initial-photos','version':1,'files':records},sort_keys=True,indent=2)+'\n').encode()
    drive=MemoryDrive();drive.files={'Initial backup/2026-10-03/original.jpg':original,
                                   'Initial backup/2026-10-03/manifest.json':raw}
    result=Run(locations,factory=drive,save=lambda:'ok',minimum=0).execute()
    assert result['state']=='success'
    assert drive.files['Initial backup/2026-10-03/manifest.json']==raw
    assert [p for p in drive.files if p.startswith('Initial backup/')]==[
        'Initial backup/2026-10-03/original.jpg','Initial backup/2026-10-03/manifest.json']
    assert load(locations.state/'initial.json')['complete']


def test_credentials_parser_error_does_not_echo_private_configuration():
    with pytest.raises(ValueError) as error:
        credentials_bytes(b'[toddlerbox]\nprivate_token_without_equals',json.loads(CONFIG)['root_folder_id'])
    assert 'private_token' not in str(error.value)


def test_interrupted_download_keeps_original_and_does_not_publish_partial(tmp_path):
    locations=installed(tmp_path);drive=MemoryDrive()
    drive.files['Photos/new.png']=png('green')
    get=drive.get
    def interrupted(remote,destination):
        if remote=='Photos/new.png':
            Path(destination).write_bytes(b'partial')
            raise TransferError('transfer-failed')
        get(remote,destination)
    drive.get=interrupted
    result=Run(locations,factory=drive,save=lambda:'ok',minimum=0).execute()
    assert result['state']=='partial'
    assert (locations.library/'example.png').read_bytes()==png()
    assert not (locations.library/'new.png').exists()
    assert list((locations.state/'staging').iterdir())==[]


def test_stalled_rclone_process_is_killed_at_job_deadline(tmp_path):
    locations=paths(tmp_path/'device');initialize(locations)
    # Synthetic executable, no provider or network. Verifies actual subprocess cleanup.
    fake=tmp_path/'stalled-rclone'
    fake.write_text('#!/bin/sh\nexec sleep 60\n');fake.chmod(0o700)
    stage=locations.state/'staging'
    remote=Rclone(locations,'synthetic_root_1234567890',stage,deadline=time.monotonic()+.2,binary=str(fake),minimum=0)
    started=time.monotonic()
    with pytest.raises(TransferError,match='timed-out'):remote.list('Photos')
    assert time.monotonic()-started<3
    assert not list(stage.iterdir())


def test_actual_read_rejects_in_place_mutation_during_snapshot(tmp_path,monkeypatch):
    path=tmp_path/'work.json';path.write_bytes(b'old')
    real=os.fstat;seen=[0]
    def mutate(fd):
        result=real(fd)
        if result.st_ino==path.stat().st_ino:
            seen[0]+=1
            if seen[0]==1:path.write_bytes(b'changed')
        return result
    monkeypatch.setattr(os,'fstat',mutate)
    with SafeTree(tmp_path) as tree,pytest.raises(ValueError,match='changed'):
        tree.read('work.json')


def test_reconnect_cannot_adopt_different_oauth_client(tmp_path):
    locations=installed(tmp_path)
    original=(locations.config/'rclone.conf').read_bytes()
    other=tmp_path/'new';other.mkdir()
    archive,checksum=package(other,files={'config.json':CONFIG,'rclone.conf':CREDENTIALS.replace(b'synthetic-client.',b'another-client.')})
    with pytest.raises(ValueError,match='OAuth client'):
        setup(locations,archive,checksum,reconnect=True,minimum=0)
    assert (locations.config/'rclone.conf').read_bytes()==original


def test_private_mac_package_helper_roundtrip_with_synthetic_originals(tmp_path):
    import subprocess
    private=tmp_path/'private';private.mkdir(mode=0o700)
    (private/'config.json').write_bytes(CONFIG)
    (private/'rclone.conf').write_bytes(CREDENTIALS)
    originals=tmp_path/'originals';originals.mkdir()
    content=large_jpeg();(originals/'large.jpg').write_bytes(content)
    archive=private/'public-fixture.toddlerbox-setup.tar.gz'
    subprocess.run([sys.executable,str(Path(__file__).parents[1]/'scripts/prepare-drive-setup.py'),
                    'package','--private-dir',str(private),'--photos',str(originals),'--output',str(archive)],
                   check=True,capture_output=True)
    locations=paths(tmp_path/'device')
    setup(locations,archive,digest(archive),minimum=0)
    assert (locations.library/'large.jpg').read_bytes()==content
    assert (originals/'large.jpg').read_bytes()==content


def test_jpeg_mpo_primary_frame_is_bounded_and_original_container_preserved(tmp_path,monkeypatch):
    from sync_fixtures import mpo
    from toddlerbox.runtime.image_safety import prepare_decoder
    raw=mpo(large=True)
    source=tmp_path/'original.JPEG';source.write_bytes(raw)
    with Image.open(io.BytesIO(raw)) as im:
        assert im.format=='MPO' and im.n_frames==2 and im.size==(8192,6075)
        im.seek(1);assert im.size==(64,48);im.load()
    loaded=[];real=ImageFile.ImageFile.load
    def bounded(image,*args,**kwargs):
        loaded.append(image.size)
        assert image.width*image.height<13_000_000
        return real(image,*args,**kwargs)
    monkeypatch.setattr(ImageFile.ImageFile,'load',bounded)
    thumb=_prepare_thumbnail(source,tmp_path/'thumb.png',(320,240))
    main=_decode_photo(source,(1366,768),upscale=True)
    validate_photo(raw,'original.JPEG')
    archive,checksum=package(tmp_path,photos={'original.JPEG':raw})
    locations=paths(tmp_path/'device');setup(locations,archive,checksum,minimum=0)
    assert (locations.library/'original.JPEG').read_bytes()==raw==source.read_bytes()
    assert thumb[1][0]<=320 and main[1][0]<=1366 and loaded
    with pytest.raises(ValueError,match='40000000'):_decode_photo(source)


def test_animated_png_stays_rejected():
    data=io.BytesIO()
    Image.new('RGB',(8,8),'red').save(data,format='PNG',save_all=True,
                                     append_images=[Image.new('RGB',(8,8),'blue')],duration=100,loop=0)
    with pytest.raises(ValueError,match='Animated PNG'):validate_photo(data.getvalue(),'animated.png')
