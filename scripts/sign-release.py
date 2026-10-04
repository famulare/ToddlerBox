"""Maintainer-only Ed25519 release signing. Never publish the private key.

uv run --with cryptography==46.0.3 python scripts/sign-release.py --generate
uv run --with cryptography==46.0.3 python scripts/sign-release.py --bundle ... --tag ... --sequence 1
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", type=Path, default=Path("build/private-signing/release-key.pem"))
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--public-key", type=Path, default=Path("system/release-public-key.pem"))
    parser.add_argument("--also-key", type=Path, action="append", default=[])
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--sequence", type=int)
    parser.add_argument("--output", type=Path, default=Path("releases/stable.json"))
    args = parser.parse_args()
    if args.generate:
        if args.key.exists() or args.public_key.exists():
            parser.error("Refusing to replace an existing signing identity")
        args.key.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        data = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        fd = os.open(args.key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        args.public_key.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        print("Signing identity created; private key remains in ignored maintainer storage.")
        return
    if not args.bundle or not args.tag or not args.sequence:
        parser.error("Bundle, tag and positive sequence required")
    if args.sequence != int(Path("system/release-sequence").read_text()):
        parser.error("Signing sequence must match the image's installed floor")
    if args.key.is_symlink() or args.key.stat().st_mode & 0o077:
        parser.error("Private key must be a private regular file")
    key = serialization.load_pem_private_key(args.key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        parser.error("Ed25519 key required")
    keys = [key]
    for path in args.also_key:
        if path.is_symlink() or path.stat().st_mode & 0o077:
            parser.error("Additional signing keys must be private regular files")
        extra = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(extra, Ed25519PrivateKey):
            parser.error("Ed25519 key required")
        keys.append(extra)
    if len(keys) > 4:
        parser.error("At most four overlapping signatures")
    source = json.loads(args.bundle.with_name(args.bundle.name + ".source.json").read_text())["source"]["content"]
    with args.bundle.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    value = {"format": 1, "channel": "stable", "sequence": args.sequence, "tag": args.tag,
             "source": source, "platform": "ubuntu24.04-x86_64", "schema": {"version": 1, "typing": 1, "paint": 1},
             "asset": "ToddlerBox-update.pyz", "bytes": args.bundle.stat().st_size, "sha256": digest}
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    if args.output.exists():
        previous = json.loads(args.output.read_text())
        if previous["sequence"] >= args.sequence and args.output.read_bytes() != data:
            parser.error("Refusing release-sequence reuse or downgrade")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    args.output.with_name(args.output.name + ".sig").write_bytes(b"".join(key.sign(data) for key in keys))
    print("Signed public release manifest.")


if __name__ == "__main__":
    main()
