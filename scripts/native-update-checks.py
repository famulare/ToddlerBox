"""Synthetic native production-runtime checks, invoked by qualify-patch-update.py.

Run as root in the isolated qualification VM, with the installed app's Python -B.
No private data or provider/network access. SDL dummy output does not qualify
Cage or speakers; the VM driver separately exercises the supervised real session.
"""
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
from unittest.mock import patch

os.environ.update(SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
os.environ.pop('TODDLERBOX_APP_CONTROL', None)
import pygame
from PIL import Image
from toddlerbox.paint.app import PaintApp, _archive_pixels, _bucket_fill
from toddlerbox.typing.app import TypingApp, _archive_payload
from toddlerbox.music.piano import Piano
from toddlerbox.runtime.control import AppChannel, SAVE_PENDING


def drain(app):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        app._service_transition()
        if app._transition_request is None and app._transition_pending is None and app._save_pending is None:
            return
        time.sleep(.002)
    raise AssertionError('Native save did not finish')


def main():
    assert importlib.metadata.version('ToddlerBox') == '0.5.1'
    assert os.geteuid() == 0  # Real root credentials for the isolated IPC sender.
    pygame.init()
    screen = pygame.display.set_mode((1366, 768))
    results = []
    with tempfile.TemporaryDirectory(prefix='tbx-native-') as directory:
        config = Path(directory) / 'config.yaml'
        config.write_text(f'data_root: {directory}/data\n')
        os.environ['KIDBOX_CONFIG'] = str(config)
        for kind, cls, function in [('paint', PaintApp, _archive_pixels), ('typing', TypingApp, _archive_payload)]:
            app = cls(screen=screen)
            if kind == 'paint':
                app.canvas_surface.fill((10, 70, 180)); app._mark_canvas_changed()
                before = pygame.image.tobytes(app.canvas_surface, 'RGB')
            else:
                for char in 'café sun':app._insert_char(char)
                before = app._record()['rich_lines']
            entered, release = threading.Event(), threading.Event()
            def blocked(*args):
                entered.set()
                assert release.wait(3)
                return function(*args)
            name = '_archive_pixels' if kind == 'paint' else '_archive_payload'
            with patch('toddlerbox.' + kind + '.app.' + name, blocked):
                app._begin_transition('new'); app._service_transition()
                assert entered.wait(1)
                try:
                    for _ in range(10):
                        app._begin_transition('new'); app._service_transition(); app._render()
                        assert app._transition_pending is not None
                    app._exit_requested = True
                    assert not app._poll_exit()
                finally:release.set()
                drain(app)
            assert app._poll_exit()
            if kind == 'paint':
                files = app._recall_archives(); assert len(files) == 1
                assert pygame.image.tobytes(pygame.image.load(str(files[0])), 'RGB') == before
                with Image.open(app.paint_dir / 'latest.png') as current:
                    assert set(current.convert('RGB').getdata()) == {(255, 255, 255)}
            else:
                files = list((app.typing_dir / 'archive').glob('*.json')); assert len(files) == 1
                assert json.loads(files[0].read_bytes())['rich_lines'] == before
                assert json.loads(app.current_path.read_bytes()) == app._record()
            app._save_worker.shutdown(wait=True)
            results.append(kind + ': blocked archive/render/repeat/Home and durable files')
        surface = pygame.Surface((1196, 736), pygame.SRCALPHA); surface.fill((30, 80, 170))
        _bucket_fill(surface, (598, 368), (200, 40, 20))
        assert pygame.image.tobytes(surface, 'RGB') == bytes((200, 40, 20)) * (1196 * 736)
        results.append('exact opaque restored-format large fill')
        from unittest.mock import Mock
        piano = Piano({}, Mock())
        assert len(piano.sounds) == len(piano.sustains) == 25
        piano._play('held', 60)
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline:
            piano.update();time.sleep(.015)
        assert any(channel.get_busy() for channel in piano.channels.values())
        piano._release('held');time.sleep(.7);piano.update()
        channels = list(piano.channels.values());piano.close()
        assert not any(channel.get_busy() for channel in channels)
        results.append('native fixed piano preparation/sustain/release/cleanup')
        endpoint = str(Path(directory) / 'controller.sock')
        clock, ready = [10.0], [False]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
            receiver.bind(endpoint);receiver.settimeout(.2)
            channel = AppChannel(endpoint, clock=lambda: clock[0])
            try:
                nonce = b'a' * 32
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as root_sender:
                    root_sender.sendto(b'sync-received', channel.socket.getsockname())
                    root_sender.sendto(b'save-current:' + nonce, channel.socket.getsockname())
                callback = lambda: True if ready[0] else SAVE_PENDING
                channel.service(callback)
                assert channel.received_at == 10 and len(channel.pending_saves) == 1
                try:receiver.recv(128)
                except socket.timeout:pass
                else:raise AssertionError('Premature durable ACK')
                ready[0] = True;channel.service(callback)
                assert receiver.recv(128) == b'save-result:' + nonce + b':ok'
            finally:channel.close()
        results.append('real Linux root SCM_CREDENTIALS receipt and deferred durable ACK')
    pygame.quit()
    print(json.dumps({'native_runtime': 'Ubuntu production Python', 'checks': results}, indent=2))
    print('NATIVE_UPDATE_CHECKS_PASS')


if __name__ == '__main__':
    main()
