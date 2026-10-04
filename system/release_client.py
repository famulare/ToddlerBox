"""Anonymous public release discovery and authenticated parent installation."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import urllib.parse
import urllib.request

from boot_recovery import STATE, atomic, latest, record, safe

CATALOG = "https://raw.githubusercontent.com/famulare/ToddlerBox/main/releases/stable.json"
HOSTS = {"raw.githubusercontent.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
PUBLIC_KEY = Path("etc/toddlerbox/release-public-key.pem")
SCHEMA = {"version": 1, "typing": 1, "paint": 1}


def check_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS or parts.username or parts.password or parts.port not in {None, 443}:
        raise ValueError("Unsupported release download destination")


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, target, maximum, *, expected_size=None):
    check_url(url)
    opener = urllib.request.build_opener(Redirects())
    request = urllib.request.Request(url, headers={"User-Agent": "ToddlerBox-parent-updater/1", "Accept-Encoding": "identity"})
    started = time.monotonic()
    size = 0
    with opener.open(request, timeout=20) as response, target.open("xb") as output:
        check_url(response.geturl())
        while data := response.read(1024 * 1024):
            size += len(data)
            if size > maximum or time.monotonic() - started > 600:
                raise ValueError("Release download exceeded limits")
            output.write(data)
        output.flush()
        os.fsync(output.fileno())
    if expected_size is not None and size != expected_size:
        raise ValueError("Incomplete release download")


def verify(data, signature, public_key):
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if len(data) > 16384 or len(signature) not in {64, 128, 192, 256} or len(public_key) > 4096:
        raise ValueError("Invalid release metadata size")
    from cryptography.exceptions import InvalidSignature
    keys = re.findall(rb"-----BEGIN PUBLIC KEY-----.*?-----END PUBLIC KEY-----", public_key, re.DOTALL)
    if not 1 <= len(keys) <= 4:
        raise ValueError("Invalid public key ring")
    valid = False
    for pem in keys:
        key = load_pem_public_key(pem)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Unsupported release key")
        for offset in range(0, len(signature), 64):
            try:
                key.verify(signature[offset:offset+64], data)
                valid = True
            except InvalidSignature:
                pass
    if not valid:
        raise ValueError("Release signature verification failed")
    value = json.loads(data)
    if set(value) != {"format", "channel", "sequence", "tag", "source", "platform", "schema", "asset", "bytes", "sha256"}:
        raise ValueError("Unsupported release metadata")
    if value["format"] != 1 or value["channel"] != "stable" or value["platform"] != "ubuntu24.04-x86_64" or value["schema"] != SCHEMA:
        raise ValueError("Release is not compatible with this installation")
    if type(value["sequence"]) is not int or not 1 <= value["sequence"] < 2 ** 63:
        raise ValueError("Invalid release sequence")
    if type(value["bytes"]) is not int or not 1 <= value["bytes"] <= 1024 ** 3:
        raise ValueError("Invalid release size")
    if value["asset"] != "ToddlerBox-update.pyz" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", value["tag"]):
        raise ValueError("Invalid release asset")
    if not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) or not re.fullmatch(r"[0-9a-f]{16}", value["source"]):
        raise ValueError("Invalid release identity")
    return value


def catalog(root=Path("/")):
    directory = safe(root, STATE / "downloads")
    directory.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        stage = Path(temporary)
        download(CATALOG, stage / "manifest", 16384)
        download(CATALOG + ".sig", stage / "signature", 256)
        value = verify((stage / "manifest").read_bytes(), (stage / "signature").read_bytes(), safe(root, PUBLIC_KEY).read_bytes())
    from appliance import maintenance_lock
    with maintenance_lock(root):
        sequence_guard(value["sequence"], root, source=value["source"], digest=value["sha256"])
        record(safe(root, STATE / "release-sequence.json"), {"sequence": value["sequence"], "source": value["source"], "sha256": value["sha256"]})
        record(safe(root, STATE / "release-candidate.json"), value)
    return value


def sequence_guard(sequence, root, *, source=None, digest=None):
    path = safe(root, STATE / "release-sequence.json")
    if not path.exists():
        raise ValueError("Missing installed update trust floor; use parent recovery")
    state = json.loads(path.read_text())
    value = state["sequence"]
    if type(value) is not int or value < 1 or type(sequence) is not int or sequence < value:
        raise ValueError("Older signed release refused")
    if sequence == value and ((state.get("source") and source != state["source"]) or (state.get("sha256") and digest != state["sha256"])):
        raise ValueError("Release sequence identity changed")


def install(root=Path("/")):
    from appliance import guard
    from update_bundle import run
    guard(root)
    value = catalog(root)
    if shutil.disk_usage(root / STATE).free < value["bytes"] * 4 + 512 * 1024 ** 2:
        raise OSError("Insufficient update/download reserve")
    directory = safe(root, STATE / "downloads")
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        bundle = Path(temporary) / "update.pyz"
        url = f"https://github.com/famulare/ToddlerBox/releases/download/{value['tag']}/{value['asset']}"
        download(url, bundle, value["bytes"], expected_size=value["bytes"])
        with bundle.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != value["sha256"]:
                raise ValueError("Release checksum mismatch")
        # The installed updater reads verified bytes; never execute the zip itself.
        result = run(bundle, value["sha256"], root=root, release_sequence=value["sequence"], release_source=value["source"])
    return result
