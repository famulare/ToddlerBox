# Private setup package, version 1

This format is shared by the Mac preparation helper and the HP importer. Do not
commit a real package, credentials, family photographs, or their manifests to this
repository or put them in an image. Use a private directory outside the checkout.

The archive is a **gzip-compressed USTAR tar (`tarfile.USTAR_FORMAT`)** containing only regular files at these
exact relative paths (no leading `./`, directory entries, PAX/GNU extensions, links or extra files):

```
manifest.json
config.json
rclone.conf
photos/library/<original filename>.jpg  # .jpeg and .png also supported, any case
```

`manifest.json` is UTF-8 JSON:

```json
{
  "format": "toddlerbox-setup",
  "version": 1,
  "package_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "created_at": "2026-10-03T00:00:00Z",
  "files": {
    "config.json": {"size": 80, "sha256": "<64 lowercase hex digits>"},
    "rclone.conf": {"size": 500, "sha256": "<64 lowercase hex digits>"},
    "photos/library/example.jpg": {"size": 1234, "sha256": "<64 lowercase hex digits>"}
  }
}
```

Sizes above are illustrative. Hashes cover the exact bytes. The manifest lists
EVERY archive file except itself. The archive's separate SHA-256 is required by
`sudo toddlerbox-sync setup PACKAGE.tar.gz --sha256 EXPECTED`; pass `--consume`
to remove the transfer archive only after installation succeeds. Keep the original
Mac photo library and an independent backup. Deleting a transfer file is not
secure erasure on flash storage.

`config.json` has exactly `{"version": 1, "root_folder_id": "<Google folder ID>"}`.
The root must have been created by rclone using the same Desktop OAuth client,
so `drive.file` permits writes. A matching single `[toddlerbox]` section in
`rclone.conf` contains `type = drive`, `client_id`, `client_secret`,
`scope = drive.readonly,drive.file`, `root_folder_id`, and the JSON `token` from
rclone authorization. Do not add other remotes, command hooks, endpoints or
service-account settings. The token and client secret are private, even though
the OAuth application is a Desktop client.

The importer rejects unsafe/duplicate/case-colliding names, nested photo paths,
symlinks, hardlinks, unexpected fields, invalid images and any hash/size mismatch.
Limits: 4,096 photos, 50 MiB per photo, 2 GiB total expanded package. JPEG decoder
downsampling permits bounded display of large originals; non-JPEG/full-resolution
pixel limits remain in force. Originals are preserved byte-for-byte.

Setup imports **photos only**. It never restores Paint or Typing. Existing files
with identical hashes are left alone; differing collisions cause refusal before
publication. Repeating a successfully installed package does not roll back refreshed
credentials or replace newer local files. The persistent device UUID is generated
on the HP, outside app releases, and is not supplied by this package.

The private imported originals are also retained for an explicit first sync's
verified `Initial backup/<package creation date>` deposit. Setup itself starts no
network job. The Mac helper can perform that same deposit explicitly before
installation. Routine sync never propagates deletions, restores cloud creations,
or prunes History. Work restoration is a separate explicit parent import.
