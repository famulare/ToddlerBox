"""Compare real first-trial/current Math rendering, excluding intended controls.

uv run --frozen python scripts/check-math-followup.py --baseline /tmp/toddlerbox-math-followup-baseline
The baseline must be an actual archive of cfd76d6, not a reconstructed algorithm.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

RUNNER = '''
import pygame, random, sys
from pathlib import Path
from toddlerbox.math.app import MathApp
from toddlerbox.math.model import Example
pygame.init()
out, version = Path(sys.argv[1]), sys.argv[2]
cases = [("numbers",0,0),("numbers",1,0),("numbers",21,0),("numbers",100,0),
         ("addition",0,0),("addition",8,7),("addition",50,50),
         ("subtraction",23,8),("subtraction",100,0),("subtraction",100,100)]
for w,h in ((800,600),(1366,768)):
 screen=pygame.display.set_mode((w,h))
 app=MathApp(screen,screen.get_rect(),pygame.time.Clock(), config={"data_root":str(out/"data")},rng=random.Random(1))
 try:
  for mode,a,b in cases:
   actual = "count" if mode=="numbers" and version=="old" else mode
   app.mode=actual; app.example=Example(actual,a,b,"cat")
   for revealed in (False,True):
    app.revealed=revealed; app.render()
    pygame.image.save(screen,out/f"{w}-{h}-{mode}-{a}-{b}-{revealed}.png")
 finally:
  if hasattr(app,"player"): app.player.cancel()
  app.art.close()
pygame.quit()
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',required=True,type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='toddlerbox-math-compare-') as scratch:
        scratch=Path(scratch)
        runner=scratch/'runner.py'
        runner.write_text(RUNNER)
        for version, source in (('old',args.baseline.resolve()),('new',root)):
            out=scratch/version
            out.mkdir()
            env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',PYTHONPATH=str(source/'src'))
            subprocess.run([sys.executable,str(runner),str(out),version],env=env,cwd=source,check=True)
        count=0
        for path in sorted((scratch/'old').glob('*.png')):
            old,new=Image.open(path).convert('RGB'),Image.open(scratch/'new'/path.name).convert('RGB')
            w=old.width
            # Mode label Count→Numbers and the new deliberate speaker are intended.
            for frame in (old,new):
                draw=ImageDraw.Draw(frame)
                draw.rectangle((w//2-80,16,w//2+79,73),fill='black')
                draw.rectangle((w//2+96,16,w//2+153,73),fill='black')
            assert old.tobytes()==new.tobytes(),path.name
            count+=1
        print(f'{count} Math frames identical outside mode label and speaker; actual cfd76d6 baseline')


if __name__=='__main__':
    main()
