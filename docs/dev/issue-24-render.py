"""Synthetic baseline/new frames. Run with the target tree on PYTHONPATH.

Capture: python docs/dev/issue-24-render.py OUTPUT
Compare: python docs/dev/issue-24-render.py --compare BASELINE NEW
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import tempfile

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import pygame


def capture(output):
    from toddlerbox.math.app import MathApp
    from toddlerbox.reading.app import ReadingApp
    from unittest.mock import Mock

    output.mkdir(parents=True, exist_ok=True)
    manifest = {}
    pygame.init()
    with tempfile.TemporaryDirectory(prefix='tbx-history-render-') as data:
        for width, height in ((480, 600), (800, 600), (1366, 768)):
            screen = pygame.display.set_mode((width, height))
            config = {'data_root': data}
            math = MathApp(screen, screen.get_rect(), pygame.time.Clock(), config=config,
                           rng=random.Random(17), player=Mock())
            reading = ReadingApp(screen, screen.get_rect(), pygame.time.Clock(), config=config,
                                 rng=random.Random(7), audio=Mock())
            try:
                for _ in range(len(reading.cards) + 2):
                    reading._service_thumbnails()
                    if reading._thumbnail_future is None:
                        break
                    reading._thumbnail_future.result(timeout=5)
                for name, app in (('math', math), ('reading', reading)):
                    for state in ('initial', 'next-hidden', 'next-revealed'):
                        if state == 'next-hidden':
                            math.change_mode() if name == 'math' else reading.next_card()
                        if state == 'next-revealed':
                            if name == 'math':
                                math.reveal()
                            else:
                                reading.player.revealed = True
                        app.render()
                        filename = f'{name}-{width}x{height}-{state}.png'
                        pygame.image.save(screen, str(output / filename))
                        manifest[filename] = hashlib.sha256(pygame.image.tobytes(screen, 'RGB')).hexdigest()
            finally:
                math.art.close()
                reading.close()
    pygame.quit()
    (output / 'frames.json').write_text(json.dumps(manifest, indent=2) + '\n')


def compare(old, new):
    manifest = json.loads((old / 'frames.json').read_text())
    results = {}
    for name in manifest:
        before, after = pygame.image.load(str(old / name)), pygame.image.load(str(new / name))
        # Intended Back card only. Existing title, Home, content and controls stay exact.
        mask = pygame.Rect(110 if name.startswith('math') else 160, 16, 48, 58)
        count = 0
        for y in range(before.get_height()):
            for x in range(before.get_width()):
                if before.get_at((x, y)) != after.get_at((x, y)):
                    assert mask.collidepoint(x, y), (name, x, y)
                    count += 1
        assert (count == 0) == ('initial' in name), (name, count)
        results[name] = {'changed_inside_back': count, 'changed_outside_back': 0}
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compare', action='store_true')
    parser.add_argument('paths', nargs='+', type=Path)
    args = parser.parse_args()
    compare(*args.paths) if args.compare else capture(*args.paths)
