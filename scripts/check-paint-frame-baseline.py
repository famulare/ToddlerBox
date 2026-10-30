#!/usr/bin/env python3
"""Compare cached Paint UI with genuine old _render code using synthetic canvases.

Run with SDL_VIDEODRIVER=dummy through uv. Does not touch appliance data.
Timing excludes real Wayland/display latency and is not hardware qualification.
"""
import argparse
import ast
import json
import os
from pathlib import Path
import statistics
import tempfile
import time

import pygame
import toddlerbox.paint.app as candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--timings', action='store_true', help='Enable in-memory diagnostic histograms')
    args = parser.parse_args()
    tree = ast.parse(args.baseline.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PaintApp')
    render = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_render')
    scope = dict(vars(candidate))
    exec(compile(ast.Module(body=[render], type_ignores=[]), str(args.baseline), 'exec'), scope)
    old_render = scope['_render']
    os.environ['SDL_VIDEODRIVER'] = 'dummy'
    os.environ['SDL_AUDIODRIVER'] = 'dummy'
    os.environ.pop('TODDLERBOX_APP_CONTROL', None)
    os.environ.pop('TODDLERBOX_DATA_ROOT', None)
    pygame.init()
    checks = 0
    with tempfile.TemporaryDirectory(prefix='tbx-frame-compare-') as tmp:
        root = Path(tmp)
        config = root / 'config.yaml'
        config.write_text(f'data_root: {root / "data"}\n')
        os.environ['KIDBOX_CONFIG'] = str(config)
        for size in [(1024, 600), (1366, 768), (1920, 1080)]:
            app = candidate.PaintApp(screen=pygame.display.set_mode(size))
            if args.timings:
                from toddlerbox.runtime.paint_timing import PaintTiming
                app._timing = PaintTiming(root / 'unused-timing.json', time.monotonic() + 600)
            for index in range(18):
                app.current_tool = ['fountain', 'round', 'eraser'][index % 3]
                app.current_size = app.size_values[index % len(app.size_values)]
                app.current_color = app.palette[index % len(app.palette)]
                app.canvas_surface.fill((index * 11, 255 - index * 7, index * 3))
                # Exercise an updated thumbnail as well as selection invalidation.
                if index % 3 == 0:
                    app._update_thumbnail_button()
                app.recall_open = index % 4 == 0
                if app.recall_open:
                    app.recall_items = []
                    app.recall_strip_rect = app.controls_rect.copy()
                old_render(app)
                expected = pygame.image.tobytes(app.screen, 'RGB')
                app._render()
                assert pygame.image.tobytes(app.screen, 'RGB') == expected, (size, index)
                # Also compare a warm cache and a changed canvas with no UI change.
                app.canvas_surface.fill((80, 120, 160))
                old_render(app)
                expected = pygame.image.tobytes(app.screen, 'RGB')
                app._render()
                assert pygame.image.tobytes(app.screen, 'RGB') == expected, (size, index, 'warm')
                checks += 2
            app.recall_open = False
            timings = {}
            for label, method in [('baseline', old_render), ('cached', candidate.PaintApp._render)]:
                samples = []
                for _ in range(220):
                    start = time.perf_counter()
                    method(app)
                    samples.append((time.perf_counter() - start) * 1000)
                timings[label] = {'median_ms': round(statistics.median(samples), 3),
                                  'p99_ms': round(sorted(samples)[int(.99 * len(samples))], 3)}
            print(json.dumps({'size': size, 'timing': timings, 'backend': 'dummy'}))
    pygame.quit()
    print(f'PASS: {checks} exact full-frame comparisons; original geometry untouched.')


if __name__ == '__main__':
    main()
