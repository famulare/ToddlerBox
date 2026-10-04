import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('installer_download', Path(__file__).parents[1]/'scripts/download-installer.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class Response(io.BytesIO):
    def geturl(self):
        return 'https://github.com/famulare/ToddlerBox/releases/download/v0.3.0/toddlerbox-installer.iso'


def fixture(monkeypatch, payload=b'synthetic iso', transferred=None):
    metadata = {'architecture': 'amd64', 'release_tag': 'v0.3.0', 'iso': {'filename': 'toddlerbox-installer.iso', 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}}
    calls = []
    def fetch(url):
        calls.append(url)
        return Response(json.dumps(metadata).encode() if url == helper.SOURCE else (payload if transferred is None else transferred))
    monkeypatch.setattr(helper, 'fetch', fetch)
    return calls


def test_anonymous_complete_download_publishes_verified_bytes(monkeypatch, tmp_path):
    calls = fixture(monkeypatch)
    target = tmp_path/'installer.iso'
    helper.download(target)
    assert target.read_bytes() == b'synthetic iso'
    assert len(calls) == 2 and list(tmp_path.iterdir()) == [target]
    helper.download(target)
    assert len(calls) == 3  # Complete matching destination does not download again.


@pytest.mark.parametrize('data', [b'truncated', b'wrong contents'])
def test_failed_download_never_publishes(monkeypatch, tmp_path, data):
    fixture(monkeypatch, transferred=data)
    with pytest.raises(ValueError): helper.download(tmp_path/'installer.iso')
    assert list(tmp_path.iterdir()) == []


def test_existing_file_and_symlink_are_preserved(monkeypatch, tmp_path):
    fixture(monkeypatch)
    target = tmp_path/'installer.iso'
    target.write_bytes(b'keep')
    with pytest.raises(ValueError): helper.download(target)
    link = tmp_path/'link.iso';link.symlink_to(target)
    with pytest.raises(ValueError): helper.download(link)
    assert target.read_bytes() == b'keep' and link.is_symlink()


@pytest.mark.parametrize('url', ['http://github.com/file', 'https://example.com/file', 'https://user@github.com/file', 'https://github.com:444/file'])
def test_untrusted_redirects_are_refused(url):
    with pytest.raises(ValueError): helper.check_url(url)
