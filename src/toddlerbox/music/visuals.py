from __future__ import annotations

import math

import pygame

from toddlerbox.ui.theme import HARMONY, INK, MELODY
SONG_COLORS = [(234, 184, 152), (224, 187, 89), (126, 174, 169),
               (151, 153, 194), (107, 163, 194), (193, 139, 160)]


def draw_song_icon(surface: pygame.Surface, rect: pygame.Rect, kind: int,
                   color: tuple = MELODY) -> None:
    """Original small vector pictures; no external artwork or font symbols."""
    cx, cy = rect.center
    r = max(4, int(min(rect.size) * 0.34))
    width = max(2, r // 7)
    if kind == 0:  # lamb
        for dx, dy in [(-.6, 0), (0, -.4), (.5, -.2), (0, .35)]:
            pygame.draw.circle(surface, color, (int(cx + dx*r), int(cy + dy*r)), int(r*.55))
        pygame.draw.ellipse(surface, INK, (cx+r*.35, cy-r*.12, r*.7, r*.6))
        for dx in [-.45, .1]:
            pygame.draw.line(surface, INK, (cx+dx*r,cy+r*.5),(cx+dx*r,cy+r*.85),width)
        pygame.draw.circle(surface, (255, 255, 255), (int(cx+r*.82), int(cy+r*.08)), max(1,width//2))
    elif kind == 1:  # star
        pts = [(cx+math.sin(i*math.pi/5)*r*(1 if i%2==0 else .45),
                cy-math.cos(i*math.pi/5)*r*(1 if i%2==0 else .45)) for i in range(10)]
        pygame.draw.polygon(surface, color, pts)
    elif kind == 2:  # sun / joy
        pygame.draw.circle(surface, color, (cx,cy), int(r*.57))
        for i in range(8):
            a = i*math.pi/4
            pygame.draw.line(surface,color,(cx+math.sin(a)*r*.8,cy+math.cos(a)*r*.8),
                             (cx+math.sin(a)*r*1.05,cy+math.cos(a)*r*1.05),width)
    elif kind == 3:  # bell
        pygame.draw.circle(surface,color,(cx,cy-int(r*.2)),int(r*.55))
        pygame.draw.polygon(surface,color,[(cx-r*.55,cy-r*.15),(cx+r*.55,cy-r*.15),
                                         (cx+r*.8,cy+r*.65),(cx-r*.8,cy+r*.65)])
        pygame.draw.circle(surface,INK,(cx,cy+int(r*.83)),max(2,int(r*.15)))
    elif kind == 4:  # boat
        pygame.draw.polygon(surface,color,[(cx-r,cy+r*.25),(cx+r,cy+r*.25),
                                         (cx+r*.55,cy+r*.8),(cx-r*.65,cy+r*.8)])
        pygame.draw.line(surface,INK,(cx,cy-r),(cx,cy+r*.2),width)
        pygame.draw.polygon(surface,color,[(cx-r*.15,cy-r),(cx-r*.15,cy+r*.05),(cx-r*.85,cy+r*.05)])
    else:  # paired dance notes
        for dx, dy in [(-.5,.3),(.5,0)]:
            pygame.draw.ellipse(surface,color,(cx+dx*r-r*.32,cy+dy*r,r*.6,r*.4))
            pygame.draw.line(surface,color,(cx+dx*r+r*.23,cy+dy*r+r*.1),
                             (cx+dx*r+r*.23,cy+dy*r-r),width)
        pygame.draw.line(surface,color,(cx-r*.27,cy-r*.7),(cx+r*.73,cy-r),width*2)


def piano_keys(rect: pygame.Rect, low: int, high: int) -> dict[int, pygame.Rect]:
    whites = [pitch for pitch in range(low, high+1) if pitch % 12 not in {1,3,6,8,10}]
    width = rect.width / len(whites)
    keys = {pitch: pygame.Rect(round(rect.x+i*width),rect.y,
                               round(rect.x+(i+1)*width)-round(rect.x+i*width),rect.height)
            for i,pitch in enumerate(whites)}
    for pitch in range(low, high+1):
        if pitch in keys:
            continue
        previous = sum(p < pitch for p in whites)
        keys[pitch] = pygame.Rect(round(rect.x+previous*width-width*.31),rect.y,
                                 round(width*.62),round(rect.height*.61))
    return keys
