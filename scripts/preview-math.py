"""Render real Math/launcher screens using public fixtures, without child data.

uv run --frozen python scripts/preview-math.py --output build/math-qa/screens
"""
import argparse
import os
from pathlib import Path
import random
import tempfile

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
from PIL import Image, ImageDraw

from toddlerbox.config import load_config
from toddlerbox.launcher import _build_buttons, _draw_launcher_frame, _load_apps
from toddlerbox.math.app import MathApp
from toddlerbox.math.model import Example
from toddlerbox.ui import theme


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/math-qa/screens"))
    args = parser.parse_args()
    cases = [("numbers-first", "numbers", 100, 0, False),
             ("numbers-revealed", "numbers", 100, 0, True),
             ("numbers-21", "numbers", 21, 0, False),
             ("add-hidden", "addition", 8, 7, False),
             ("add-8-7", "addition", 8, 7, True),
             ("add-50-50", "addition", 50, 50, True),
             ("subtract-23-8", "subtraction", 23, 8, True),
             ("subtract-100-0", "subtraction", 100, 0, True),
             ("subtract-100-100", "subtraction", 100, 100, True),
             ("zero-hidden", "numbers", 0, 0, False),
             ("zero-revealed", "numbers", 0, 0, True)]
    pygame.init()
    try:
        for size in ((800,600),(1366,768)):
            out = args.output/f"{size[0]}x{size[1]}"
            out.mkdir(parents=True, exist_ok=True)
            screen = pygame.display.set_mode(size)
            with tempfile.TemporaryDirectory(prefix="toddlerbox-math-preview-") as temporary:
                config = load_config()
                config["data_root"] = temporary
                apps = _load_apps(config)
                _draw_launcher_frame(screen, theme.BACKGROUND, apps, _build_buttons(apps, screen.get_rect()))
                pygame.image.save(screen, out/"launcher.png")
                app = MathApp(screen, screen.get_rect(), pygame.time.Clock(), config=config, rng=random.Random(1))
                try:
                    for name, mode, a, b, revealed in cases:
                        app.mode = mode
                        app.example = Example(mode, a, b, "cat")
                        app.revealed = revealed
                        app.render()
                        pygame.image.save(screen, out/f"{name}.png")
                finally:
                    app.art.close()
            sheet = Image.new("RGB", (1200, 920), theme.BACKGROUND)
            draw = ImageDraw.Draw(sheet)
            names = ["launcher", "numbers-revealed", "numbers-21", "add-hidden", "add-8-7", "add-50-50",
                     "subtract-23-8", "subtract-100-100", "zero-revealed"]
            for i, name in enumerate(names):
                picture = Image.open(out/f"{name}.png")
                picture.thumbnail((390,270))
                x, y = (i%3)*400+5, (i//3)*300+26
                sheet.paste(picture, (x,y))
                draw.text((x,y-18), name, fill=theme.INK)
            sheet.save(args.output/f"{size[0]}x{size[1]}-overview.png")
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
