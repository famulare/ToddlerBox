import os
import secrets
import socket
import struct
import time


def request_save(address='/run/toddlerbox-control.sock', *, timeout=5):
    nonce = secrets.token_hex(16).encode()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            client.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            client.bind(f'\0toddlerbox-sync-{os.getpid()}-{secrets.token_hex(12)}')
            deadline = time.monotonic() + timeout
            client.settimeout(timeout)
            client.sendto(b'save-current:' + nonce, address)
            while time.monotonic() < deadline:
                client.settimeout(max(.001, deadline-time.monotonic()))
                message, ancillary, flags, _ = client.recvmsg(128, socket.CMSG_SPACE(12))
                if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                    continue
                uid = next((struct.unpack('3i', data[:12])[1] for level, kind, data in ancillary
                            if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS and len(data) >= 12), None)
                if uid == 0 and message.startswith(b'save-result:' + nonce + b':'):
                    result = message.rsplit(b':',1)[1].decode('ascii', errors='replace')
                    if result in {'ok','failed','timeout','unavailable'}:
                        return result
    except TimeoutError:
        return 'timeout'
    except OSError:
        return 'unavailable'
    return 'timeout'
