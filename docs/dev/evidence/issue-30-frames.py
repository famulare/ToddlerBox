"""Compare genuine baseline/new Math frames (synthetic illustrations only).

First extract baseline app.py to /tmp/issue30-baseline-math.py using git show.
Run with SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy and project PYTHONPATH.
"""
import importlib.util, random
import pygame
from toddlerbox.math.app import MathApp
from toddlerbox.math.model import Example
spec=importlib.util.spec_from_file_location('baseline_math', '/tmp/issue30-baseline-math.py')
old=importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
pygame.init()
count=0
for size in [(800,600),(1366,768),(480,600)]:
 screen=pygame.display.set_mode(size)
 apps=[cls(screen,screen.get_rect(),pygame.time.Clock(),config={'data_root':'/tmp/issue30-synthetic'},rng=random.Random(17)) for cls in [old.MathApp,MathApp]]
 for mode,a,b in [('numbers',100,0),('addition',50,50),('subtraction',100,99)]:
  for revealed in [False,True]:
   frames=[]
   for app in apps:
    app.mode=mode; app.example=Example(mode,a,b,'cat'); app.revealed=revealed; app.render()
    frames.append(pygame.image.tobytes(screen,'RGB'))
   assert frames[0]==frames[1],(size,mode,revealed)
   count+=1
 for app in apps: app.art.close()
print(f'{count} genuine baseline/new complete frames byte-identical')
pygame.quit()
