# Parent setup and maintenance

The appliance installer first asks for a parent password on its console. Then
log into **parent** on the normal Ubuntu desktop. **ToddlerBox Setup & Maintenance**
opens automatically until setup is complete, and remains in the applications menu.
There are no default passwords or Git credentials.

This is deliberately a simple terminal program. Follow its prompts; open Ubuntu
Wi-Fi or Sound settings when offered. Checks can be recorded as passed, failed
or skipped. Offline use and skipping Drive are valid. Previously recorded checks
are retained unless you explicitly redo them.

The recovery check requires a real supervised child session: let it run at least
ten seconds, try input and volume keys, then hold Ctrl+Alt+Home for two seconds.
Authenticate as parent again and finish setup. Reboot during this test returns
to unfinished parent setup. Finishing requires the successful recovery check;
other hardware limitations can be accepted explicitly.

The program offers:

- Status, including setup results, system services, disk space, update/recovery
  state, Drive's last successful completion and Ubuntu reboot requirement.
- Check/install qualified public GitHub releases, accept a tested candidate,
  rollback and retry an interrupted recovery.
- Explicit Ubuntu package updates and repair of interrupted package configuration.
- Drive setup/import/sync/status/reconnect. A chosen private setup package has its
  checksum calculated automatically and each member validated by the importer.
- A reviewed local support report and a prefilled public GitHub issue.

Save parent desktop work before installing, rolling back or retrying recovery:
session restarts can end that desktop session. Test the candidate child session,
return through parent login, and select **Accept tested update**. Until acceptance,
one previous working system/app pair remains the recovery target; another update
is refused. The candidate has at most two explicit test entries. Failed application
startup/exhausted supervision or controller failure restores that pair and opens
parent recovery. New drawings and Typing documents remain separate from releases.

Downloads require networking; ordinary local use, status and rollback do not.
Check/install uses public HTTPS without GitHub login. GitHub's `gh` CLI is included
for convenience, but its authentication is not part of the update path. Integrity
and authenticity checks are automatic; no manual release-hash comparison is needed.

Ubuntu updates use signed normal Noble repositories, including security fixes.
They are parent initiated: no unattended package installs or automatic reboots.
Check monthly and reboot when requested. These package changes are outside
ToddlerBox bundle rollback. Retain the recovery USB and back up child work.
The persistent GRUB recovery entry survives Ubuntu kernel/menu regeneration;
normal Ubuntu remains the default, with the five-second menu available at boot.
If package state is inconsistent, complete **Ubuntu updates** before installing
another bundle or returning to child mode. A network/mirror failure with verified
consistent package state leaves offline child use available. Local conffiles are
preserved and maintenance output is visible in the parent terminal.

Status/report remain available when installation recovery is blocked. A corrupt
backup is refused, rather than guessed at; try **Retry recovery** after fixing
storage problems. The boot recovery menu, independent console and USB remain
available if graphical recovery cannot start. No multi-file update promises a
whole-disk atomic transaction or reversal of Ubuntu packages.

Reports contain an allowlist of states/versions, not photos, drawings, document
text, credentials, raw logs, Wi-Fi names, serial numbers or private paths. Review
the report before choosing to post publicly. GitHub requires browser login to
submit an issue; no token is stored by ToddlerBox. Without network/account access,
keep `~/ToddlerBox-support.json` and share it later.

Drive remains explicit-only (`ctrl-alt-s`, held two seconds, or parent sync action).
Setup, updates and network connection do not trigger it. Its account-wide read
scope and private credentials are explained in [Drive privacy](drive-sync-privacy.md).
Software/public reports and private family data have separate handling.
