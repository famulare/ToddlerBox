# Temporary candidate transfer

The builder's ordinary GitHub release upload endpoint rejected even a 255-byte
file with HTTP 400 `Bad Content-Length`, using both `gh` and explicit-length
HTTP/1.1 curl. Public installer bytes are temporarily available as **unreferenced
Git blobs**. No binary chunks are in any branch, commit or application history.
They may be garbage-collected; the recipient must promptly verify and publish
the complete ISO as an ordinary GitHub release asset. JSON manifests here are
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
that built image identity. The live Pages source should switch to main/docs only
after merge and verification by the parent maintainer.
