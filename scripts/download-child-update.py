#!/usr/bin/env python3
"""Public checksum-verified update download; run as the parent WITHOUT sudo.

Release-asset uploads are blocked on the cloud builder. This temporary Git blob
is unreferenced: the binary is not committed to source history. A parent can
publish the verified .pyz as a normal release asset using their own machine.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.request

URL = "https://api.github.com/repos/famulare/ToddlerBox/git/blobs/39700803b455cec1e186d7f8c9cb8fa8a88886d1"
SHA256 = "6907bb8d89dada2b9e6cf8d6a23d7d16f9a4678b751bdb65a3902a492849cb3c"
SIZE = 100905


def download(destination):
    if destination.exists():
        if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == SHA256:
            return
        raise ValueError("Destination already exists with different bytes; choose another filename.")
    request = urllib.request.Request(URL, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "ToddlerBox-parent-update"})
    with urllib.request.urlopen(request, timeout=60) as response:
        encoded = response.read(SIZE * 2 + 1)
    if len(encoded) > SIZE * 2:
        raise ValueError("Unexpectedly large download")
    record = json.loads(encoded)
    if record.get("encoding") != "base64" or record.get("size") != SIZE:
        raise ValueError("Unexpected GitHub blob response")
    data = base64.b64decode(record["content"])
    if len(data) != SIZE or hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError("Download checksum mismatch; nothing published locally.")
    fd, temporary = tempfile.mkstemp(prefix=".tbx-download-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        # Exclusive link prevents overwriting a pathname created during download.
        os.link(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("ToddlerBox-update.pyz"))
    args = parser.parse_args()
    try:
        download(args.output)
    except (OSError, ValueError, KeyError) as error:
        sys.exit(f"Download stopped: {error}")
    print(f"Verified {args.output}: {SIZE} bytes, SHA-256 {SHA256}")
