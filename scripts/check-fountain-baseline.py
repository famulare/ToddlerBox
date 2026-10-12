#!/usr/bin/env python3
"""Compare synthetic fountain strokes with genuine source from a baseline checkout.

Usage: uv run --frozen python scripts/check-fountain-baseline.py BASELINE
BASELINE is a checkout directory or its src/toddlerbox/paint/app.py file.
Only use trusted baseline source: its functions are compiled and executed.
No display, child data, saved paintings, or baseline installation is required.
"""
from __future__ import annotations

import argparse
import ast
import math
import random
from pathlib import Path
from types import SimpleNamespace

import pygame

import toddlerbox.paint.app as candidate


def load_baseline(path: Path):
    """Execute original function bodies, without reimplementing the old renderer."""
    if path.is_dir():
        path = path / "src/toddlerbox/paint/app.py"
    source = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    scope = {"pygame": pygame, "math": math, "Point": tuple, "Color": tuple}
    for name in ("FOUNTAIN_DENSITY", "FOUNTAIN_SMOOTHING"):
        assignment = next(
            node for node in source.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
        )
        scope[name] = ast.literal_eval(assignment.value)
    functions = [
        next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == name)
        for name in ("_fountain_width_for_direction", "_draw_fountain_segment")
    ]
    app_class = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "PaintApp")
    functions.append(next(
        node for node in app_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_handle_pointer_move"
    ))
    for function in functions:
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), scope)
    return scope["_handle_pointer_move"], path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="trusted baseline checkout or Paint source file")
    args = parser.parse_args()
    baseline_move, baseline_path = load_baseline(args.baseline)
    rng = random.Random(31)
    compared = 0
    for flags in (0, pygame.SRCALPHA):
        for trial in range(200):
            start = (rng.randrange(-20, 181), rng.randrange(-20, 131))
            size = rng.choice((1, 3, 6, 12, 25, 48))
            color = tuple(rng.randrange(256) for _ in range(3))
            surfaces = [pygame.Surface((160, 110), flags=flags) for _ in range(2)]
            for surface in surfaces:
                surface.fill((255, 255, 255))

            def state(surface):
                return SimpleNamespace(
                    canvas_surface=surface,
                    canvas_rect=pygame.Rect(0, 0, 160, 110),
                    current_stroke=candidate.Stroke("fountain", size, color, [start]),
                    _mark_canvas_changed=lambda: None,
                )

            old, new = map(state, surfaces)
            for step in range(8):
                end = start if step == 2 else (rng.randrange(-20, 181), rng.randrange(-20, 131))
                baseline_move(old, end)
                candidate.PaintApp._handle_pointer_move(new, end)
                compared += 1
                label = f"flags={flags}, stroke={trial}, event={step}, size={size}"
                if pygame.image.tobytes(surfaces[0], "RGBA") != pygame.image.tobytes(surfaces[1], "RGBA"):
                    raise SystemExit(f"FAIL: different rendered pixels ({label})")
                if (old.current_stroke.points != new.current_stroke.points
                        or old.current_stroke.fountain_width != new.current_stroke.fountain_width):
                    raise SystemExit(f"FAIL: different stroke state ({label})")
    print(f"Baseline: {baseline_path}")
    print(f"Candidate: {candidate.__file__}")
    print(f"PASS: exact pixels and stroke state for {compared} events / 400 strokes; "
          "RGB and SRCALPHA, widths 1–48, clipping and reversals; seed=31")


if __name__ == "__main__":
    main()
