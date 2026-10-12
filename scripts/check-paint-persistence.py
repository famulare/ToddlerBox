"""Compare genuine checkout code with identical synthetic paint/typing inputs.

uv run --frozen python scripts/check-paint-persistence.py CHECKOUT OUTPUT
Run separately for baseline and candidate; compare observables.json exactly.
Timing data is diagnostic, not a hardware performance claim. No private media.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(args.checkout.resolve() / 'src'))
    import pygame
    from toddlerbox.paint.app import PaintApp, _bucket_fill, RecallItem
    from toddlerbox.typing.app import TypingApp, RecallSession, Glyph
    pygame.init()
    screen = pygame.display.set_mode((1366, 768))
    observable, timing = {}, {}
    def digest(surface):
        return hashlib.sha256(pygame.image.tobytes(surface, 'RGBA')).hexdigest()
    def drain(app):
        if not hasattr(app, '_service_transition'):
            return
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            app._service_transition()
            if app._transition_pending is None and app._transition_request is None and app._save_pending is None:
                return
            time.sleep(.001)
        raise RuntimeError('save deadline exceeded')
    rng = random.Random(42)
    for case in range(90):
        depth = (8, 16, 24, 32)[case % 4]
        image = pygame.Surface((37, 29), depth=depth) if case < 45 else pygame.Surface((37, 29), pygame.SRCALPHA)
        if case >= 75:
            image.set_colorkey((128, 128, 128))
        colors = [(0, 0, 0), (255, 255, 255), (128, 128, 128)]
        for y in range(29):
            for x in range(37):
                color = colors[rng.randrange(3)] if case > 3 else colors[(x + y + case) % 3]
                image.set_at((x, y), (*color, rng.choice((0, 120, 255))) if case >= 45 else color)
        _bucket_fill(image, (rng.randrange(37), rng.randrange(29)), (36, 80, 180))
        observable[f'fill-{case}'] = digest(image)
    durations = []
    for _ in range(7):
        image = pygame.Surface((1196, 736)); image.fill('white')
        started = time.perf_counter()
        _bucket_fill(image, (598, 368), (36, 80, 180))
        durations.append((time.perf_counter() - started) * 1000)
    observable['fill-large'] = digest(image)
    timing['fill-ms'] = durations
    with tempfile.TemporaryDirectory() as directory:
        config = {'data_root': directory, 'paint': {'palette': [[36, 80, 180]]}}
        with patch('toddlerbox.paint.app.load_config', return_value=config):
            paint = PaintApp(screen=screen)
        for tool in ('round', 'fountain', 'eraser'):
            paint._reset_canvas()
            if tool == 'eraser':
                paint.canvas_surface.fill((60, 100, 150))
            paint.current_tool = tool
            start = (paint.canvas_rect.left + 90, paint.canvas_rect.top + 100)
            paint._handle_pointer_down(start)
            durations = []
            renders = []
            for i in range(240):
                pos = (start[0] + i * 3, start[1] + round(50 * __import__('math').sin(i / 10)))
                started = time.perf_counter()
                paint._handle_pointer_move(pos)
                durations.append((time.perf_counter() - started) * 1000)
                if i % 8 == 0:
                    started = time.perf_counter(); paint._render()
                    renders.append((time.perf_counter() - started) * 1000)
            paint._handle_pointer_up()
            paint._render()
            observable[f'pen-{tool}'] = digest(paint.canvas_surface)
            observable[f'pen-frame-{tool}'] = digest(screen)
            pygame.image.save(screen, str(args.output / f'pen-{tool}.png'))
            paint._undo(); observable[f'undo-{tool}'] = digest(paint.canvas_surface)
            paint._redo(); observable[f'redo-{tool}'] = digest(paint.canvas_surface)
            timing[f'pen-{tool}-max-ms'] = max(durations)
            timing[f'pen-{tool}-median-ms'] = statistics.median(durations)
            timing[f'render-{tool}-max-ms'] = max(renders)
        for size in paint.size_values:
            paint._reset_canvas()
            paint.current_tool, paint.current_size = 'fountain', size
            start = (paint.canvas_rect.left + 30, paint.canvas_rect.top + 40)
            paint._handle_pointer_down(start)
            long_moves = []
            for i in range(20):
                pos = (paint.canvas_rect.right - 30 if i % 2 == 0 else start[0],
                       start[1] + (i * 27) % 600)
                started = time.perf_counter(); paint._handle_pointer_move(pos)
                long_moves.append((time.perf_counter() - started) * 1000)
                observable[f'fountain-long-{size}-{i}'] = digest(paint.canvas_surface)
            paint._handle_pointer_up()
            timing[f'fountain-long-{size}-median-ms'] = statistics.median(long_moves)
            timing[f'fountain-long-{size}-max-ms'] = max(long_moves)
        started = time.perf_counter()
        if hasattr(paint, '_begin_transition'):
            paint._handle_pointer_down(paint.action_buttons['new'].rect.center, defer_saves=True)
            paint._service_transition()
        else:
            paint._handle_pointer_down(paint.action_buttons['new'].rect.center)
        timing['paint-new-dispatch-ms'] = (time.perf_counter() - started) * 1000
        drain(paint)
        observable['paint-new'] = digest(paint.canvas_surface)
        archive = paint._recall_archives()[0]
        observable['paint-archive'] = digest(pygame.image.load(str(archive)).convert_alpha())
        if hasattr(paint, '_begin_transition'):
            paint._handle_recall_selection(RecallItem(None, archive), defer_saves=True)
        else:
            paint._handle_recall_selection(RecallItem(None, archive))
        drain(paint)
        paint._render()
        observable['paint-recalled'] = digest(paint.canvas_surface)
        observable['paint-recalled-frame'] = digest(screen)
        observable['paint-latest'] = digest(pygame.image.load(str(paint.paint_dir / 'latest.png')).convert_alpha())
        with patch('toddlerbox.typing.app.load_config', return_value=config):
            typing = TypingApp(screen=screen)
        for char in 'café sun\nABC':
            typing._insert_char(char)
        typing._render(); observable['typing-frame'] = digest(screen)
        observable['typing-current'] = typing._record()
        started = time.perf_counter()
        if hasattr(typing, '_begin_transition'):
            typing._begin_transition('new'); typing._service_transition()
        else:
            assert typing._archive_session(); typing._clear_text(); assert typing._save_current()
        timing['typing-new-dispatch-ms'] = (time.perf_counter() - started) * 1000
        drain(typing)
        observable['typing-new-disk'] = json.loads(typing.current_path.read_bytes())
        records = list((typing.typing_dir / 'archive').glob('*.json'))
        observable['typing-archive-lines'] = json.loads(records[0].read_bytes())['rich_lines']
        typing.recall_items = [RecallSession('recall', 'B', [[Glyph('B', 50, 'bold')]])]
        if hasattr(typing, '_begin_transition'):
            typing._apply_recall(0, defer_saves=True)
        else:
            typing._apply_recall(0)
        drain(typing)
        typing._render(); observable['typing-recalled-frame'] = digest(screen)
        observable['typing-recalled-disk'] = typing.current_path.read_bytes().decode('utf8')
        for app in (paint, typing):
            if getattr(app, '_save_worker', None):
                app._save_worker.shutdown(wait=True)
    (args.output / 'observables.json').write_text(json.dumps(observable, indent=2, sort_keys=True) + '\n')
    (args.output / 'timings.json').write_text(json.dumps(timing, indent=2, sort_keys=True) + '\n')
    print(json.dumps(timing, indent=2))
    pygame.quit()


if __name__ == '__main__':
    main()
