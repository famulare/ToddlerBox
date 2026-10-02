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
    _send(b"frame")


def shutdown_complete() -> None:
    """Acknowledge only after the activity has saved and released its resources."""
    _send(b"shutdown-complete")


def _send(message: bytes) -> None:
    address = os.environ.get("TODDLERBOX_HEALTH_SOCKET")
    if not address:
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            client.setblocking(False)
            client.sendto(message, address)
    except OSError:
        # The system service handles missing health reports; never show an error UI.
        pass
