"""Authenticated root-to-app requests, serviced only on the normal UI thread."""
from __future__ import annotations

import math
import os
import secrets
import socket
import struct
import time
from functools import lru_cache

import pygame
from toddlerbox.ui import theme


class AppChannel:
    def __init__(self, address: str, *, clock=time.monotonic):
        self.address, self.clock = address, clock
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            self.socket.setblocking(False)
            self.socket.bind(f"\0toddlerbox-app-{os.getpid()}-{secrets.token_hex(12)}")
        except BaseException:
            self.socket.close()
            raise
        self.received_at = float('-inf')
        self.serviced: list[bytes] = []

    def report_frame(self):
        try:
            self.socket.sendto(b'app-frame', self.address)
        except OSError:
            pass

    def service(self, save_current=None):
        for _ in range(16):
            try:
                message, ancillary, flags, _ = self.socket.recvmsg(128, socket.CMSG_SPACE(12))
            except (BlockingIOError, OSError):
                break
            if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                continue
            credentials = next((struct.unpack('3i', value[:12]) for level, kind, value in ancillary
                                if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS
                                and len(value) >= 12), None)
            if credentials is None or credentials[1] != 0:
                continue
            if message == b'sync-received':
                self.received_at = self.clock()
            elif message.startswith(b'save-current:'):
                nonce = message[13:]
                if len(nonce) != 32 or any(c not in b'0123456789abcdef' for c in nonce):
                    continue
                if nonce in self.serviced:
                    continue
                self.serviced = (self.serviced + [nonce])[-16:]
                try:
                    saved = save_current is None or save_current() is True
                except Exception:
                    saved = False
                try:
                    self.socket.sendto(b'save-result:' + nonce + (b':ok' if saved else b':failed'), self.address)
                except OSError:
                    pass

    def close(self):
        self.socket.close()


_channel = None


def channel():
    global _channel
    if _channel is None and os.environ.get('TODDLERBOX_APP_CONTROL') == '1':
        address = os.environ.get('TODDLERBOX_HEALTH_SOCKET')
        if address:
            try:
                _channel = AppChannel(address)
            except OSError:
                pass
    return _channel


def frame_complete():
    active = channel()
    if active is not None:
        active.report_frame()


@lru_cache(maxsize=1)
def shooting_star():
    art = pygame.Surface((48, 48), pygame.SRCALPHA)
    pygame.draw.line(art, (*theme.ACCENT, 150), (3, 37), (26, 15), 4)
    pygame.draw.line(art, (*theme.ACCENT, 90), (6, 45), (28, 24), 3)
    pygame.draw.line(art, (*theme.MELODY, 120), (2, 27), (20, 9), 3)
    points = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        radius = 14 if i % 2 == 0 else 6
        points.append((31 + math.cos(angle)*radius, 17 + math.sin(angle)*radius))
    pygame.draw.polygon(art, theme.HARMONY, points)
    pygame.draw.lines(art, theme.INK, True, points, 1)
    return art


def draw_receipt(screen, received_at, now):
    age = now - received_at
    if not 0 <= age < 1.5:
        return
    art = shooting_star()
    if age > 1.2:
        art = art.copy()
        art.set_alpha(round(255 * (1.5 - age) / .3))
    home = theme.home_rect(screen.get_rect())
    screen.blit(art, (home.left - 12 - 48, home.centery - 24))


def before_flip(screen, save_current=None):
    """Screen-only overlay; callers never pass artwork or document surfaces."""
    active = channel()
    if active is not None:
        active.service(save_current)
        draw_receipt(screen, active.received_at, active.clock())
