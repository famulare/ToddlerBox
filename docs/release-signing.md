# Public release signing and distribution

Fresh appliance images embed an Ed25519 public key ring and an initial signed
release-sequence floor. Ordinary public update metadata is discovered at
`releases/stable.json` on main, with its detached `stable.json.sig`. The manifest
names only a fixed public repository's `ToddlerBox-update.pyz` asset, source ID,
platform, v1 data schema, size, SHA-256, stable channel and increasing sequence.
Unknown fields/platforms/schemas and backwards or changed sequence identities
are refused. The installed verifier checks the signature before fetching payloads;
the installed updater reads the verified zip and never executes its bootstrap.

Only designate a release stable after suite, image and fresh-install/update/recovery
qualification. GitHub latest/prerelease flags alone are not sufficient. Maintain
the detached manifest and release assets as one reviewed publication; transient
manifest/signature inconsistency fails safely and can be retried.

The maintainer private key is outside source and images in ignored
`build/private-signing/release-key.pem`, mode 0600. Docker contexts exclude `build`.
Back this key up through a private maintainer channel before cleaning that directory;
never commit it, upload it as a release asset or attach it to a public issue.
Laptops need only the public key. Account Git credentials are not a substitute
for the release signature, and are not required on a laptop.

For a new qualified release, increase `system/release-sequence` before building:

```sh
uv run --frozen python system/build-update.py --cage build/child-controls-qa/toddlerbox-cage --app build/<image>/toddlerbox-app-<id>.tar.gz --output build/<image>/ToddlerBox-update.pyz
uv run --frozen --with cryptography==46.0.3 python scripts/sign-release.py --bundle build/<image>/ToddlerBox-update.pyz --tag <qualified-tag> --sequence <number>
```

Publish the qualified ISO, combined bundle, checksums, source/package identities,
and the signed manifest/signature. The bootstrap zip remains useful for advanced
administration, but old images without the embedded verifier/key require a
separately trusted migration or the new installer; they cannot authenticate a
downloaded executable through that executable itself.

For planned key rotation, generate a new private key in private storage using
`--generate --key <private-path> --public-key <new-public-path>`. Include both public
PEMs in `system/release-public-key.pem` for a qualified transition release. Sign
its metadata with the old key and `--also-key <new-private-path>`; the verifier
accepts up to four trusted public keys and four detached signatures. Continue
dual signing for at least six months before removing the old key/signature.
Release sequences remain increasing through rotation and rollback. Skipped
transition releases may require trusted USB migration after the overlap closes.
Compromised-key recovery requires an independently trusted new image/key; do not
claim an update signed solely by the compromised key fixes that trust.

The resident recovery protocol, boot units and destination allowlist are outside
ordinary replaceable bundles. A future change to that protocol requires a
separately qualified migration/new image. Never weaken signature verification,
apt signatures, path checks or compatibility guards to make an update install.
