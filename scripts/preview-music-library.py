"""Render Music's public song rail at small/HP sizes without child data."""
import os
from pathlib import Path
import tempfile
from unittest.mock import Mock

os.environ['SDL_VIDEODRIVER']='dummy'
os.environ['SDL_AUDIODRIVER']='dummy'
import pygame
from PIL import Image,ImageDraw
from toddlerbox.music.app import MusicApp
from toddlerbox.ui import theme

out=Path('build/music-expansion-qa/screens');out.mkdir(parents=True,exist_ok=True)
pygame.init()
try:
    for size in ((800,600),(1366,768)):
        screen=pygame.display.set_mode(size)
        with tempfile.TemporaryDirectory(prefix='toddlerbox-music-preview-') as temp:
            audio=Mock();audio.position.return_value=5000;audio.busy.return_value=True
            app=MusicApp(screen,screen.get_rect(),pygame.time.Clock(),config={'data_root':temp},audio=audio)
            try:
                for name,index,free in (('first',0,False),('last',17,False),('free',17,True)):
                    app.free_play=free
                    app.player.select(index)
                    app.player._position=5000
                    if free:app.player.close()
                    app.render()
                    pygame.image.save(screen,out/f'{size[0]}-{name}.png')
            finally:
                app.player.close();app.piano.close()
        sheet=Image.new('RGB',(1200,270),theme.BACKGROUND);draw=ImageDraw.Draw(sheet)
        for i,name in enumerate(('first','last','free')):
            pic=Image.open(out/f'{size[0]}-{name}.png');pic.thumbnail((390,245))
            sheet.paste(pic,(i*400+5,20));draw.text((i*400+5,3),name,fill=theme.INK)
        sheet.save(out/f'{size[0]}-overview.png')
finally:pygame.quit()
