"""Synthetic public fixtures only; none of these tokens authorize a provider."""
import hashlib
import io
import json
from pathlib import Path
import tarfile

from PIL import Image
from system.tbx_sync.state import Paths

ROOT_ID='synthetic_root_1234567890'
CONFIG=json.dumps({'version':1,'root_folder_id':ROOT_ID}).encode()
TOKEN=json.dumps({'access_token':'synthetic-not-a-real-access-token','refresh_token':'synthetic-not-a-real-refresh-token',
                  'token_type':'Bearer','expiry':'2099-01-01T00:00:00Z'})
CREDENTIALS=('''[toddlerbox]
type = drive
client_id = synthetic-client.apps.googleusercontent.com
client_secret = synthetic-not-a-real-secret
scope = drive.readonly,drive.file
root_folder_id = '''+ROOT_ID+'\ntoken = '+TOKEN+'\n').encode()


def png(color='orange',size=(30,20)):
    result=io.BytesIO();Image.new('RGB',size,color).save(result,format='PNG')
    return result.getvalue()


def typing(text):
    return json.dumps({'version':1,'rich_lines':[[{'char':c,'size':25,'style':'plain'} for c in text]],
                       'cursor':[0,len(text)],'size':25,'style':'plain'}).encode()


def paths(root):
    root=Path(root)
    for name in ['config','state','data','data/paint','data/typing/archive','data/photos/library']:
        (root/name).mkdir(parents=True,exist_ok=True,mode=0o700)
    return Paths(root/'config',root/'state',root/'data')


def package(root,*,photos=None,files=None,mutate=None):
    root=Path(root)
    files=files if files is not None else {'config.json':CONFIG,'rclone.conf':CREDENTIALS,
              **{'photos/library/'+name:data for name,data in (photos or {'example.png':png()}).items()}}
    manifest={'format':'toddlerbox-setup','version':1,'package_id':'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
              'created_at':'2026-10-03T00:00:00Z',
              'files':{name:{'size':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in files.items()}}
    members=[('manifest.json',json.dumps(manifest).encode()),*files.items()]
    if mutate:members=mutate(members)
    archive=root/'synthetic.toddlerbox-setup.tar.gz'
    with tarfile.open(archive,'w:gz',format=tarfile.USTAR_FORMAT) as out:
        for name,data in members:
            if isinstance(name,tarfile.TarInfo):
                out.addfile(name,io.BytesIO(data) if data else None)
            else:
                info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o600
                out.addfile(info,io.BytesIO(data))
    return archive,hashlib.sha256(archive.read_bytes()).hexdigest()


class MemoryDrive:
    """Copy-only remote with fault injection and immutable source capture."""
    def __init__(self):
        self.files={}
        self.operations=[]
        self.before_put=None
        self.fail=None
        self.extra_entries={}

    def __call__(self,*args,**kwargs):return self

    def _fault(self):
        if self.fail:raise self.fail

    def list(self,path,*,recursive=False):
        self._fault()
        entries=[]
        for name,data in self.files.items():
            if name.startswith(path+'/'):
                relative=name[len(path)+1:]
                if recursive or '/' not in relative:
                    entries.append({'Path':relative,'Name':relative,'Size':len(data),'IsDir':False,
                                    'Hashes':{'md5':hashlib.md5(data).hexdigest()}})
                else:
                    directory=relative.split('/')[0]
                    if not any(e['Path']==directory for e in entries):
                        entries.append({'Path':directory,'Name':directory,'Size':-1,'IsDir':True})
        return entries+self.extra_entries.get(path,[])

    def get(self,remote,destination):
        self._fault();self.operations.append(('get',remote))
        Path(destination).write_bytes(self.files[remote])

    def put(self,source,remote,*,immutable=False):
        self._fault()
        if self.before_put:self.before_put(source,remote)
        data=Path(source).read_bytes()
        if immutable and remote in self.files and self.files[remote]!=data:
            from system.tbx_sync.remote import TransferError
            raise TransferError('immutable-conflict')
        self.operations.append(('put',remote,data))
        self.files[remote]=data

    def verify(self,remote,expected):
        self._fault()
        assert hashlib.sha256(self.files[remote]).hexdigest()==expected
        self.operations.append(('verify',remote))


def large_jpeg(width=8192,height=6075):
    """Valid neutral grayscale JPEG, built from repeated zero-DCT MCUs.

    Only an 8x8 source is encoded; no full-sized pixel image is allocated.
    """
    import struct
    tiny=io.BytesIO();Image.new('L',(8,8),128).save(tiny,format='JPEG',quality=75,optimize=False)
    data=bytearray(tiny.getvalue())
    frame=data.index(b'\xff\xc0')
    data[frame+5:frame+9]=struct.pack('>HH',height,width)
    scan=data.index(b'\xff\xda')
    start=scan+2+int.from_bytes(data[scan+2:scan+4],'big')
    assert data[start:-2]==b'\x2b'  # DC category 0 (00), AC EOB (1010), pad 11.
    count=((width+7)//8)*((height+7)//8)
    full,remainder=divmod(count,4)
    entropy=b'\x28\xa2\x8a'*full  # four 001010 MCUs = 24 bits.
    if remainder:
        bits='001010'*remainder
        bits+='1'*((-len(bits))%8)
        entropy+=int(bits,2).to_bytes(len(bits)//8,'big')
    return bytes(data[:start])+entropy.replace(b'\xff',b'\xff\x00')+b'\xff\xd9'


def large_png(width=8192,height=6075):
    """Stream uniform scanlines through zlib, never construct a full image."""
    import struct,zlib
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    encoder=zlib.compressobj()
    row=b'\0'*(width+1)
    compressed=b''.join(encoder.compress(row) for _ in range(height))+encoder.flush()
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,0,0,0,0))+
            chunk(b'IDAT',compressed)+chunk(b'IEND',b''))
