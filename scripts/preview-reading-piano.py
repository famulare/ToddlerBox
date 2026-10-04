"""Repeatable synthetic screenshots; no family images or physical audio claim."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
from pathlib import Path
import tempfile
import random
import pygame
from toddlerbox.reading.app import ReadingApp
from toddlerbox.music.app import MusicApp
from toddlerbox.ui import theme


class Audio:
    def play(self, *args): pass
    def stop(self): pass
    def position(self): return 3500
    def busy(self): return True


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "docs/images"
    output.mkdir(exist_ok=True)
    pygame.init()
    screen = pygame.display.set_mode((1366,768))
    with tempfile.TemporaryDirectory() as data:
        config = {"data_root":data}
        reading = ReadingApp(screen, screen.get_rect(), pygame.time.Clock(), config=config,
                             audio=Audio(), rng=random.Random(1))
        reading.select_card(next(card for card in reading.cards if card.text == "brush"))
        reading.render()
        pygame.image.save(screen, output / "reading-word-rail.png")
        reading.rail_images = True
        reading.player.revealed = True
        reading.render()
        pygame.image.save(screen, output / "reading-picture-rail.png")
        music = MusicApp(screen, screen.get_rect(), pygame.time.Clock(), config=config, audio=Audio())
        music.player.select(0)
        music.player.update()
        for finger,pitch in enumerate((60,64)):
            x,y = music.keys[pitch].center
            music.handle_event(pygame.event.Event(pygame.FINGERDOWN,x=x/1366,y=y/768,touch_id=1,finger_id=finger))
        music.render()
        pygame.image.save(screen, output / "music-play-along.png")
        music.piano.close()
        music.free_play = True
        music.player.close()
        music.render()
        pygame.image.save(screen, output / "music-free-play.png")
        music.piano.close()
        # Contact sheet for picture/word correspondence and original artwork review.
        cells = pygame.Surface((1000, ((len(reading.cards)+7)//8)*130))
        cells.fill(theme.BACKGROUND)
        for i,card in enumerate(reading.cards):
            x,y=(i%8)*125,(i//8)*130
            image=pygame.image.load(str(card.image)).convert_alpha()
            image=pygame.transform.smoothscale(image,(92,92))
            cells.blit(image,(x+16,y+4))
            word=theme.ui_font(18).render(card.text,True,theme.INK)
            cells.blit(word,word.get_rect(center=(x+62,y+112)))
        pygame.image.save(cells,root/"build/reading-piano-qa/word-gallery.png")
    pygame.quit()


if __name__ == "__main__": main()
