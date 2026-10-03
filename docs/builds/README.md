# Qualified installer and transfer record

The normal download is the [qualified Drive sync prerelease](https://github.com/famulare/ToddlerBox/releases/tag/candidate-drive-sync-374e31452f4672ea).
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
