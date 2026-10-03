#!/usr/bin/env python3
"""Compare actual baseline/current renders in identical subprocess environments.

uv run python scripts/check-sync-rendering.py --baseline build/drive-sync-qa/baseline-source
The baseline must be a git archive/worktree of the actual old commit, with assets.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def render(source, output, state):
    sys.path.insert(0,str(source/'src'))
    os.chdir(source)
    os.environ['SDL_VIDEODRIVER']='dummy'
    os.environ['SDL_AUDIODRIVER']='dummy'
    os.environ.pop('TODDLERBOX_APP_CONTROL',None)
    import pygame
    import yaml
    from PIL import Image,ImageDraw
    from toddlerbox import launcher
    from toddlerbox.ui import theme
    from toddlerbox.paint.app import PaintApp
    from toddlerbox.typing.app import TypingApp
    from toddlerbox.photos.app import PhotosApp,_prepare_thumbnail
    from toddlerbox.music.app import MusicApp
    from toddlerbox.reading.app import ReadingApp
    from toddlerbox.runtime import health
    assert Path(launcher.__file__).is_relative_to(source)
    class Audio:
        def play(self,*args):pass
        def position(self):return 4000
        def busy(self):return True
        def stop(self):pass
    class First:
        def choice(self,items):return items[0]
    class Receipt:
        received_at=10
        def clock(self):return {'inactive':12,'active':10,'expired':11.5}[state]
        def service(self,save_current=None):pass
        def report_frame(self):pass
    if state!='baseline':
        from toddlerbox.runtime import control
        control._channel=Receipt()
    pygame.display.init();pygame.font.init()
    for size in [(1024,600),(1366,768)]:
        out=output/f'{size[0]}x{size[1]}';out.mkdir(parents=True)
        with tempfile.TemporaryDirectory() as temporary:
            data=Path(temporary)/'data'
            library=data/'photos/library';library.mkdir(parents=True)
            fixture=Image.new('RGB',(320,240),'#7ba4a5')
            ImageDraw.Draw(fixture).ellipse((90,45,230,185),fill='#efbc62')
            fixture.save(library/'synthetic.png')
            config=yaml.safe_load((source/'config.yaml').read_text())
            config['data_root']=str(data)
            cfg=Path(temporary)/'config.yaml';cfg.write_text(yaml.safe_dump(config))
            os.environ['KIDBOX_CONFIG']=str(cfg)
            screen=pygame.display.set_mode(size);clock=pygame.time.Clock()
            def shot(name):pygame.image.save(screen,out/f'{name}.png')
            apps=launcher._load_apps(config)
            launcher._draw_launcher_frame(screen,theme.BACKGROUND,apps,launcher._build_buttons(apps,screen.get_rect()));shot('launcher')
            paint=PaintApp(screen=screen)
            pygame.draw.lines(paint.canvas_surface,theme.MELODY,False,[(80,120),(180,240),(280,120)],13)
            paint._canvas_revision+=1
            paint._render();shot('paint')
            assert paint._autosave_latest()
            (out/'saved-paint.png').write_bytes((data/'paint/latest.png').read_bytes())
            typing=TypingApp(screen=screen)
            for char in 'Silly cat':typing._insert_char(char)
            typing._render();shot('typing')
            assert typing._save_current()
            (out/'saved-typing.json').write_bytes((data/'typing/current.json').read_bytes())
            photos=PhotosApp(screen=screen)
            import time
            for _ in range(200):
                photos._service_preparation()
                if photos.current_image is not None:break
                time.sleep(.01)
            assert photos.current_image is not None
            photos._render();shot('photos');photos.close()
            # The real thumbnail pipeline, with any screen overlay already active.
            _prepare_thumbnail(library/'synthetic.png',out/'saved-thumb.jpg',(160,160))
            # Exercise actual run-loop flip hooks, not an isolated call to the overlay.
            old_get,old_flip=pygame.event.get,pygame.display.flip
            for name,app in [('music',MusicApp(screen,screen.get_rect(),clock,config=config,audio=Audio())),
                             ('reading',ReadingApp(screen,screen.get_rect(),clock,config=config,audio=Audio(),rng=First()))]:
                calls=[0]
                def events():
                    calls[0]+=1
                    return [] if calls[0]==1 else [pygame.event.Event(pygame.QUIT)]
                def flip():shot(name)
                pygame.event.get=events;pygame.display.flip=flip
                health._stop_requested=False
                app.run()
            pygame.event.get,pygame.display.flip=old_get,old_flip
            for pool in (paint._save_worker,paint._recall_worker):
                if pool:pool.shutdown(wait=True)
    pygame.quit()


def compare(baseline, output):
    from PIL import Image,ImageChops,ImageDraw
    source=Path(__file__).resolve().parents[1]
    script=Path(__file__).resolve()
    output.mkdir(parents=True,exist_ok=True)
    for state,root in [('baseline',baseline),('inactive',source),('active',source),('expired',source)]:
        subprocess.run([sys.executable,str(script),'--render',str(root),'--output',str(output/state),'--state',state],check=True)
    counts={'unchanged_frames':0,'overlay_frames':0,'saved_outputs_identical':0}
    for size in [(1024,600),(1366,768)]:
        folder=f'{size[0]}x{size[1]}'
        for original in (output/'baseline'/folder).iterdir():
            for state in ['inactive','active','expired']:
                candidate=output/state/folder/original.name
                if original.name.startswith('saved-'):
                    assert candidate.read_bytes()==original.read_bytes(),(state,original.name)
                    counts['saved_outputs_identical']+=1
                else:
                    a,b=Image.open(original).convert('RGB'),Image.open(candidate).convert('RGB')
                    bounds=ImageChops.difference(a,b).getbbox()
                    if state=='active':
                        # home_rect is fixed 64px, margin13 in this source contract;
                        # query the actual function instead of duplicating geometry.
                        from toddlerbox.ui import theme
                        import pygame
                        home=theme.home_rect(pygame.Rect(0,0,*size))
                        allowed=(home.left-60,home.centery-24,home.left-12,home.centery+24)
                        assert bounds and bounds[0]>=allowed[0] and bounds[1]>=allowed[1] and bounds[2]<=allowed[2] and bounds[3]<=allowed[3],(original.name,bounds,allowed)
                        counts['overlay_frames']+=1
                    else:
                        assert bounds is None,(state,original.name,bounds)
                        counts['unchanged_frames']+=1
        sheet=Image.new('RGB',(1536,720),'#f5f0e6');draw=ImageDraw.Draw(sheet)
        for i,name in enumerate(['launcher','paint','photos','typing','music','reading']):
            im=Image.open(output/'active'/folder/f'{name}.png');im.thumbnail((500,320))
            x,y=(i%3)*512+6,(i//3)*360+28
            sheet.paste(im,(x,y));draw.text((x,y-20),name.title(),fill='#263d3c')
        sheet.save(output/f'{folder}-overview.png')
    (output/'results.json').write_text(json.dumps(counts,indent=2)+'\n')
    print(json.dumps(counts))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--output',type=Path,default=Path('build/drive-sync-qa/rendering'))
    parser.add_argument('--render',type=Path)
    parser.add_argument('--state')
    args=parser.parse_args()
    if args.render:render(args.render.resolve(),args.output.resolve(),args.state)
    elif args.baseline:compare(args.baseline.resolve(),args.output.resolve())
    else:parser.error('--baseline is required')
