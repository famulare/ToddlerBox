# ToddlerBox 0.3.0 installer

[Download release 0.3.0](https://github.com/famulare/ToddlerBox/releases/tag/v0.3.0).
The ordinary `toddlerbox-installer.iso` asset is for Ubuntu 24.04 x86-64 UEFI;
Secure Boot is outside the supported configuration. See [validation](../../VALIDATION.md)
and [private backup/reinstallation](../reinstall.md) before erasing the HP.

For an automatic checksum/size check without GitHub login or manual hash comparison,
run this public helper **without sudo** on the downloading computer:

```sh
curl -fL https://raw.githubusercontent.com/famulare/ToddlerBox/main/scripts/download-installer.py -o download-installer.py
python3 download-installer.py ~/Downloads/ToddlerBox-0.3.0.iso
```

It uses standard-library Python, preserves a different existing destination and
publishes only a complete verified download. Flash the resulting ISO with Etcher
and let write validation finish. Initial download trusts GitHub HTTPS; later
appliance updates additionally use the verification key embedded in the installer.
The normal parent update path needs neither Git credentials nor developer tooling.

Built source `0799b122a5aa9c84e15a79a2bcdb087195957c9e`, content ID
`8776dfa5476b7156`; [source/checksum record](../releases/installer-8776dfa5476b7156.json)
and [pinned packages](../releases/packages-8776dfa5476b7156.tsv).
ISO: **1,552,717,824 bytes**, SHA-256
`c8ea365bcacfe5d6957cea14152a68edd9ac168a4214e01022ccf72160a4a235`.
The combined signed update is **67,630,331 bytes**, SHA-256
`1e8f4839cfac6bc732071068ed460a18fa2fedb344753e78ed7277d3cd829bf9`.
Later documentation/delivery commits are separate from this exact build identity.

## Builder transport record

The managed builder rejects ordinary release uploads with HTTP 400
`Bad Content-Length`. The explicit-only publication workflow reconstructs public
unreferenced chunks, checks literal complete hashes, then publishes ordinary
release assets. There are no binary chunks in Git history, private inputs,
automatic runs or scheduled publishing. The temporary chunk helper requires
maintainer `gh` authentication and is not the normal installer/update path.
Unreferenced chunks may be garbage-collected; retain normal release assets.

The `1e136b40a252ca52` and `5046c47496917dd3` prototypes were not qualified;
their metadata records rejection/supersession, and they are not installation choices.

# Previous qualified play installer

Source `9952ee142fd128aeec326161c01ddeb91166b155`, content ID
`a60a9ddeca41e3f6`. ISO: 1,542,178,816 bytes; SHA-256
`33bf906226fa2db87d87d5e325c4951bbe94a93ca9c911d7822430824ef10066`.
The missing compositor directory is fixed in the image recipe; first installation
verified the release path and absolute `/var/lib/toddlerbox` data root.

[Release](https://github.com/famulare/ToddlerBox/releases/tag/candidate-play-a60a9ddeca41e3f6)
and [source/checksum metadata](../releases/installer-a60a9ddeca41e3f6.json).
The normal ISO, SHA256SUMS and source.json release assets are published. GitHub
independently reports the expected complete ISO digest. The explicit-only
publication workflow succeeded in [run 37170634224](https://github.com/famulare/ToddlerBox/actions/runs/37170634224).
The builder upload endpoint still rejects direct uploads; 184 unreferenced public
Git blobs supplied temporary transport before that job published ordinary assets:

```sh
uv run --no-project --python python3 scripts/download-public-installer.py \
  docs/builds/a60a9ddeca41e3f6-transfer.json /chosen/path/toddlerbox-installer.iso
```

The explicit-only **Publish qualified installer** Actions workflow can reassemble
this exact public manifest, verify the literal complete checksum, and upload normal
release assets. It has no push, pull-request, timer or automatic triggers. No
private setup packages, credentials or family data are inputs. Public chunks remain
temporary transport and do not enter binary Git history.

See [the private backup/reinstall checklist](../reinstall.md) before erasing the HP.

## Earlier Drive sync installer / archived transfer record

The earlier normal download is the [qualified Drive sync prerelease](https://github.com/famulare/ToddlerBox/releases/tag/candidate-drive-sync-374e31452f4672ea).
Use its `toddlerbox-installer.iso`, `SHA256SUMS` and `source.json`. The installer
is 1,530,040,320 bytes, with SHA-256
`def9b5cfcd55e4ebc2c66938b5b43006f584ae49d620ddd1ab3d5d607bf92fa4`.
Fresh installed-VM qualification is complete; physical HP and USB acceptance
remain pending. See [the validation record](../../VALIDATION.md).

The metadata below records the temporary route used to bring the public image
from the builder to the Mac before publishing the ordinary release asset.

The builder's ordinary GitHub release upload endpoint rejected even a 255-byte
file with HTTP 400 `Bad Content-Length`, using both `gh` and explicit-length
HTTP/1.1 curl. Public installer bytes were transferred as **unreferenced
Git blobs**. No binary chunks are in any branch, commit or application history.
They may be garbage-collected; use the ordinary release asset for recovery.
JSON manifests here are
small transfer metadata, not permanent binary hosting.

```sh
uv run --frozen python scripts/download-public-installer.py \
  docs/builds/374e31452f4672ea-transfer.json /chosen/path/toddlerbox-installer.iso
```

The helper checks each chunk and the complete ISO SHA-256/length, resumes a
partial transfer, and preserves any different existing destination. It needs
normal authenticated `gh` access for the request count. It never flashes a disk.
Consult the PR and VALIDATION.md for qualification status before installation.

Image source: `bf48568a02ead0e7da80ac34c93d9e047d412ad5`, content ID
`374e31452f4672ea`. Later documentation/consent-site commits are separate from
that built image identity. GitHub Pages now uses `main /docs`; the existing
homepage and privacy URLs were compared with the merged source.

