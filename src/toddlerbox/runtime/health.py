"""Only a completed UI frame feeds the independent system watchdog."""
from __future__ import annotations

import os
import signal
import socket
import time

_last_frame = 0.0
_stopping = False


def _stop(_signum: int, _frame: object) -> None:
    global _stopping
    _stopping = True


def install_shutdown_handlers() -> None:
    signal.signal(signal.SIGTERM, _stop)


def stopping() -> bool:
    return _stopping


def frame_complete() -> None:
    global _last_frame
    address = os.environ.get("TODDLERBOX_HEALTH_SOCKET")
    now = time.monotonic()
    if not address or now - _last_frame < 1:
        return
    _last_frame = now
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            client.setblocking(False)
            client.sendto(b"frame", address)
    except OSError:
        # The system service handles missing health reports; never show an error UI.
        pass
