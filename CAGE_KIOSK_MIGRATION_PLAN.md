# Cage system migration

The former tty-autologin migration plan is superseded by the bootable Ubuntu
recipe in [system/README.md](system/README.md).

The selected implementation uses GDM as the only graphical session manager.
The child session runs Cage directly on the seat. Parent mode runs the ordinary
Ubuntu GNOME session under the separate `parent` account. No login-shell kiosk
autostart, GDM masking, nested Cage, or global keyd remapping is part of this build.

A root-owned controller monitors event-loop heartbeats and observes the parent
escape chord independently of the app. It stops automatic child login after a
bounded number of failures. Boot-menu parent recovery is available before the
application starts.

This describes the new image recipe. It does not establish which session the HP
currently runs. Hardware migration begins only after VM qualification and a
backup of that machine. See the validation record and remaining checks in the
system documentation.
