"""Render actual old/new apps under identical inputs; compare JSON RGBA hashes.

uv run --frozen python scripts/check-picture-preload.py CHECKOUT OUTPUT
Uses bundled Reading illustrations and generated Photos only. A baseline
archive is sufficient; no reconstructed old renderer and no family media.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import time
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.checkout.resolve() / "src"))
    import pygame
    from PIL import Image, ImageDraw
    from toddlerbox.reading.app import ReadingApp
    from toddlerbox.photos.app import PhotosApp
    from toddlerbox.math.app import MathApp
    from toddlerbox.math.model import Example

    args.output.mkdir(parents=True, exist_ok=False)
    pygame.init()
    screen = pygame.display.set_mode((1366, 768))
    frames, timings = {}, {}

    def capture(name):
        frames[name] = hashlib.sha256(pygame.image.tobytes(screen, "RGBA")).hexdigest()
        pygame.image.save(screen, str(args.output / f"{name}.png"))

    with tempfile.TemporaryDirectory() as temporary:
        config = {"data_root": temporary}
        reading = ReadingApp(screen, screen.get_rect(), pygame.time.Clock(),
                             config=config, audio=Mock(), rng=random.Random(7))
        reading.select_card(reading.cards[0])
        if hasattr(reading, "_service_thumbnails"):
            for _ in range(len(reading.cards) + 2):
                reading._service_thumbnails()
                if reading._thumbnail_future is None:
                    break
                reading._thumbnail_future.result(timeout=5)
        for pictures in (False, True):
            reading.rail_images = pictures
            for offset in (0, 304, 1900):
                reading.rail_offset = offset
                started = time.perf_counter()
                reading.render()
                name = f"reading-{'pictures' if pictures else 'words'}-{offset}"
                timings[name] = (time.perf_counter() - started) * 1000
                capture(name)
        # Exercise the actual default, rather than forcing the selected view.
        default = ReadingApp(screen, screen.get_rect(), pygame.time.Clock(),
                             config=config, audio=Mock(), rng=random.Random(7))
        default.select_card(default.cards[0])
        if hasattr(default, "_service_thumbnails"):
            for _ in range(len(default.cards) + 2):
                default._service_thumbnails()
                if default._thumbnail_future is None:
                    break
                default._thumbnail_future.result(timeout=5)
        default.render()
        capture("reading-default")
        frames["default-picture-view"] = default.rail_images
        library = Path(temporary) / "photos/library"
        library.mkdir(parents=True)
        for i in range(12):
            image = Image.new("RGB", (480, 360), "#f8f6ed")
            drawing = ImageDraw.Draw(image)
            drawing.ellipse((130, 60, 350, 280), fill=(50 + i*10, 130, 150), outline="#293c49", width=4)
            image.save(library / f"synthetic-{i:02}.png")
        with patch("toddlerbox.photos.app.load_config", return_value=config):
            photos = PhotosApp(screen=screen)
        for _ in range(30):
            if photos._future is not None:
                photos._future.result(timeout=5)
            photos._service_preparation(list(range(12)))
            if photos._future is None:
                break
        for offset in (0, 304, 1000):
            photos.scroll_y = offset
            photos._render()
            capture(f"photos-{offset}")
        frames["original-photo-hashes"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                           for path in sorted(library.glob("*.png"))}
        photos.close()
        cases = [("numbers", 0, 0), ("numbers", 1, 0), ("numbers", 21, 0), ("numbers", 100, 0),
                 ("addition", 0, 0), ("addition", 8, 7), ("addition", 50, 50),
                 ("subtraction", 23, 8), ("subtraction", 100, 0), ("subtraction", 100, 100)]
        for width, height in ((800, 600), (1366, 768)):
            screen = pygame.display.set_mode((width, height))
            math = MathApp(screen, screen.get_rect(), pygame.time.Clock(), config=config,
                           rng=random.Random(7), player=Mock())
            for mode, a, b in cases:
                math.mode, math.example = mode, Example(mode, a, b, "cat")
                for revealed in (False, True):
                    math.revealed = revealed
                    math.render()
                    capture(f"math-{width}-{mode}-{a}-{b}-{revealed}")
            math.art.close()
        taps = {}
        for name, down_dx, up_dx in (("light-center", 0, 0), ("light-edge", 38, 38),
                                     ("light-drift", 0, 28), ("drag", 0, 38)):
            math = MathApp(screen, screen.get_rect(), pygame.time.Clock(), config=config,
                           rng=random.Random(7), player=Mock())
            before = math.example
            x, y = math.next_rect.center
            for kind, dx in ((pygame.FINGERDOWN, down_dx), (pygame.FINGERUP, up_dx)):
                math.handle_event(pygame.event.Event(kind, x=(x+dx)/screen.get_width(),
                                  y=y/screen.get_height(), touch_id=1, finger_id=1, pressure=.001))
            taps[name] = before != math.example
            math.art.close()
        frames["math-next-taps"] = taps
        if hasattr(reading, "close"):
            reading.close()
            default.close()
        else:
            reading.player.close()
            default.player.close()
    pygame.quit()
    (args.output / "observables.json").write_text(json.dumps(frames, indent=2) + "\n")
    (args.output / "render-ms.json").write_text(json.dumps(timings, indent=2) + "\n")
    print(json.dumps(frames, indent=2))


if __name__ == "__main__":
    main()
