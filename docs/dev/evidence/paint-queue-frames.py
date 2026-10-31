"""Synthetic off/armed pen/eraser frames and saved bytes; run with chosen PYTHONPATH."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
import pygame
from toddlerbox.paint.app import PaintApp
from toddlerbox.runtime.paint_timing import PaintTiming


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(armed):
    with tempfile.TemporaryDirectory() as folder:
        config = Path(folder) / 'config.yaml'
        config.write_text(f'data_root: {folder}/data\npaint:\n  palette: [[20, 40, 70]]\n')
        os.environ['KIDBOX_CONFIG'] = str(config)
        pygame.init()
        screen = pygame.display.set_mode((1366, 768))
        app = PaintApp(screen=screen)
        if armed:
            app._timing = PaintTiming(Path(folder) / 'unused', time.monotonic() + 60)
            # The historical class has no native queue sampler.
            if hasattr(app._timing, 'queue_probe'):
                from toddlerbox.runtime.touch_queue_timing import TouchQueueTiming
                app._timing.queue_probe = TouchQueueTiming.available()
        frames, batches = [], []
        def button(kind, pos):
            return pygame.event.Event(kind, pos=pos, button=1, touch=False)
        x, y = app.canvas_rect.center
        for tool, offset in [('fountain', 0), ('eraser', 12), ('round', 24), ('fountain', 36)]:
            target = app.tool_buttons[tool].rect.center
            batches += [[button(pygame.MOUSEBUTTONDOWN, target)],
                        [button(pygame.MOUSEBUTTONUP, target)],
                        [button(pygame.MOUSEBUTTONDOWN, (x, y + offset))],
                        [pygame.event.Event(pygame.MOUSEMOTION, pos=(x + 40, y + offset),
                                            rel=(40, 0), buttons=(1, 0, 0), touch=False)],
                        [button(pygame.MOUSEBUTTONUP, (x + 40, y + offset))]]
        pending = iter(batches)
        consumed = [0]
        original_render = app._render
        def events(**_kwargs):
            consumed[0] += 1
            return next(pending)
        def render():
            original_render()
            frames.append(digest(pygame.image.tobytes(screen, 'RGB')))
        try:
            with patch.object(pygame.event, 'get', events), patch.object(app, '_render', render), \
                    patch('toddlerbox.paint.app.health.stopping', lambda: consumed[0] >= len(batches)), \
                    patch('toddlerbox.paint.app.health.frame_complete', lambda: None):
                app._run()
            assert app._autosave_latest()
            return {'frames': frames, 'png': digest((app.paint_dir / 'latest.png').read_bytes())}
        finally:
            for worker in [app._save_worker, app._recall_worker]:
                if worker is not None:
                    worker.shutdown(wait=True, cancel_futures=True)
            pygame.quit()


if __name__ == '__main__':
    print(json.dumps({'off': run(False), 'armed': run(True)}, sort_keys=True))
