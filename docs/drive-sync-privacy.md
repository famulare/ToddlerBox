# ToddlerBox private Google Drive use

ToddlerBox is a personal, offline-first application for a family's own computer.
Its optional Drive connection copies family photographs and the child's Paint
and Typing files to and from that family's Google account. There is no ToddlerBox
hosted account, analytics service, advertising, sale of data, or use of Google user data for AI model training. The public source
repository and image builder receive no Google credentials or family files.

## Permission and folder boundary

Parents authorize their **own Google Desktop OAuth client** with two scopes:
`drive.readonly` and `drive.file`. **Read-only access is account-wide**; Google does
not limit that permission to one folder. ToddlerBox's transfer commands use the
saved `root_folder_id` to confine normal operations to the app-created
`ToddlerBox` folder. This software boundary does not narrow the OAuth grant.

`drive.file` permits writes to files created by or otherwise explicitly authorized
for that OAuth application. ToddlerBox creates its root with rclone using the
same client, then writes the child's creations, preserved previous versions and
original-photo backup within that root. It does not request unrestricted Drive
write access. Transfers use Google's services and are subject to the parent's
Google account settings and Google's privacy terms.

## Local storage and explicit transfers

Authorization tokens and client configuration stay in private Mac preparation
storage and, after installation, in a root-owned `0700` configuration directory
on the HP (`0600` credential files). The child account cannot read them. Private
setup archives contain credentials and original photographs: keep them outside
source/image directories, verify their SHA-256, and remove transfer copies only
after successful installation. Removal is not a claim of secure flash erasure.

Only a parent's explicit sync request starts a transfer. There are no scheduled,
boot-triggered, network-triggered or automatic retry jobs. Bounded retries occur
only within a requested job. The shooting star means the request was received;
it is not a success report. Parent status retains transfer counts, failures and
the last successful completion. It contains no learning scores or analytics.

## Ordinary files, retention and deletion

`Photos` supplies downloaded JPG/JPEG/PNG originals. `Creations/<device UUID>`
contains Paint PNGs, authoritative Typing JSON and UTF-8 text exports.
`History/<device UUID>/<run>` preserves cloud versions before replacement.
`Initial backup/<date>` holds verified original photographs. These are ordinary
files that a parent can inspect or copy without ToddlerBox. Restore is an explicit
parent import; routine sync never overwrites local Paint or Typing work.

Copies do not propagate deletions. Removing a cloud photograph does not remove its
local copy; removing a local creation does not delete the cloud copy. History and
initial backups have no automatic expiration or pruning. Parents manage retention
and deletion directly in Drive and on the HP; a later explicit copy can recreate
a file that still exists at its source. Google Drive's own Trash/retention rules
also apply. Removing authorization does not delete previously copied files.

Parents can revoke the OAuth application's access through their Google Account
and remove the local private sync configuration. Reconnecting uses a new token
for the same folder/client and does not require reinstalling ToddlerBox or erasing
the child's work. See [setup and operation](drive-sync.md) for the maintenance flow.

Use of Google API information follows the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
including Limited Use requirements. The public consent website is hosted by
GitHub Pages, which may process ordinary access records under GitHub's privacy
policy; the site has no application tracking scripts or private family data.
Do not post credentials or private files in the public issue tracker.
