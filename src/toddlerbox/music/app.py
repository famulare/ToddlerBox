from __future__ import annotations

import os
from pathlib import Path

import pygame

from toddlerbox.config import load_config
from toddlerbox.music.library import load_library
from toddlerbox.music.playback import MusicPlayer
from toddlerbox.music.visuals import HARMONY, INK, MELODY, SONG_COLORS, draw_song_icon, piano_keys
from toddlerbox.paths import get_data_root
from toddlerbox.runtime import get_runtime_logger, health
from toddlerbox.ui import theme
from toddlerbox.ui.common import (PointerInput, create_fullscreen_window, draw_home_button,
                                  is_escape_chord, is_primary_pointer_event, pointer_event_pos)

BACKGROUND, PAPER, MUTED = theme.BACKGROUND, theme.PAPER, theme.MUTED
FOCUS_EVENTS = {getattr(pygame,"WINDOWFOCUSLOST",-1), getattr(pygame,"WINDOWFOCUSGAINED",-2),
                getattr(pygame,"APP_DIDENTERFOREGROUND",-3)}


class MusicApp:
    def __init__(self, screen: pygame.Surface, screen_rect: pygame.Rect,
                 clock: pygame.time.Clock, *, config=None, audio=None):
        self.screen, self.rect, self.clock = screen, screen_rect, clock
        self.config = load_config() if config is None else config
        self.logger = get_runtime_logger(get_data_root(self.config))
        options = self.config.get("music", {})
        library = Path(__file__).resolve().parents[3] / "assets" / "music"
        tracks, self.low, self.high = load_library(library, self.logger)
        self.player = MusicPlayer(tracks, self.logger, audio=audio,
                                  volume=options.get("volume", 0.25),
                                  autoplay=bool(options.get("autoplay", True)),
                                  latency_ms=options.get("latency_ms", 0))
        self.pointer = PointerInput()
        self.font = theme.ui_font(20)
        self.small = theme.ui_font(16)
        self.heading = theme.ui_font(max(24, min(34, screen_rect.h//19)), bold=True)
        self.title = theme.ui_font(24, bold=True)
        self._layout()
        self._static = self._background()
        self._scan_index = 0
        self._scan_track = -1
        self._scan_time = -1.0

    def _layout(self) -> None:
        margin = max(12, min(24, self.rect.w//44))
        rail = max(170, min(236, round(self.rect.w*.23)))
        self.home_rect = theme.home_rect(self.rect)
        self.rail_rect = pygame.Rect(margin, 100, rail-margin, self.rect.h-100-margin)
        self.keyboard_rect = pygame.Rect(rail+margin*2, self.rect.h-margin-min(150,self.rect.h//4),
                                         self.rect.w-rail-margin*3, min(150,self.rect.h//4))
        self.field_rect = pygame.Rect(self.keyboard_rect.x, 109, self.keyboard_rect.w,
                                     self.keyboard_rect.y-109)
        self.keys = piano_keys(self.keyboard_rect, self.low, self.high)
        self.pause_rect = pygame.Rect(self.rail_rect.x,self.rail_rect.bottom-100,self.rail_rect.w,48)
        self.auto_rect = pygame.Rect(self.rail_rect.x,self.rail_rect.bottom-44,self.rail_rect.w,44)
        count = max(1, len(self.player.tracks))
        card_height = min(58, (self.pause_rect.top-self.rail_rect.top-16-(count-1)*7)//count)
        self.song_rects = [pygame.Rect(self.rail_rect.x,self.rail_rect.y+i*(card_height+7),
                                      self.rail_rect.w,card_height) for i in range(len(self.player.tracks))]
        self.song_labels = []
        self.song_kinds = []
        ids = ["mary", "twinkle", "ode", "frere", "row", "minuet"]
        short_titles = dict(zip(ids,["Little Lamb", "Twinkle", "Ode to Joy", "Frère Jacques", "Row Your Boat", "Minuet in G"]))
        for i, (track, rect) in enumerate(zip(self.player.tracks, self.song_rects)):
            label = short_titles.get(track.id,track.title)
            self.song_kinds.append(ids.index(track.id) if track.id in ids else 5)
            size = 20
            font = theme.ui_font(size)
            while font.size(label)[0] > rect.w-65 and size > 12:
                size -= 1
                font = theme.ui_font(size)
            self.song_labels.append(font.render(label,True,INK))

    def _background(self) -> pygame.Surface:
        surface = pygame.Surface(self.rect.size)
        surface.fill(BACKGROUND)
        surface.blit(self.heading.render("Music",True,INK),(self.rail_rect.x,30))
        pygame.draw.rect(surface,PAPER,self.field_rect,border_radius=18)
        for pitch, key in self.keys.items():
            if pitch % 12 not in {1,3,6,8,10}:
                pygame.draw.line(surface,(239,238,228),(key.x,self.field_rect.y+16),
                                 (key.x,self.field_rect.bottom),1)
        for i in range(1,4):
            y = self.field_rect.y+self.field_rect.h*i//4
            pygame.draw.line(surface,(245,242,233),(self.field_rect.x+1,y),(self.field_rect.right-1,y),1)
        return surface

    def _draw_controls(self) -> None:
        for i,rect in enumerate(self.song_rects):
            selected = i == self.player.index
            theme.card(self.screen, rect, selected=selected)
            icon_rect = pygame.Rect(rect.x+7,rect.y+4,46,rect.h-8)
            kind = self.song_kinds[i]
            draw_song_icon(self.screen,icon_rect,kind,SONG_COLORS[kind])
            self.screen.blit(self.song_labels[i],(rect.x+59,rect.centery-self.song_labels[i].get_height()//2))
        playing = self.player.state in {"playing", "gap"}
        pygame.draw.rect(self.screen,INK,self.pause_rect,border_radius=14)
        x,y = self.pause_rect.x+27,self.pause_rect.centery
        if playing:
            for dx in [-5,5]:
                pygame.draw.rect(self.screen,PAPER,(x+dx-2,y-9,5,18),border_radius=2)
        else:
            pygame.draw.polygon(self.screen,PAPER,[(x-6,y-10),(x-6,y+10),(x+10,y)])
        text = self.font.render("Pause" if playing else "Play",True,PAPER)
        self.screen.blit(text,(self.pause_rect.x+54,y-text.get_height()//2))
        theme.card(self.screen, self.auto_rect, fill=theme.PANEL)
        label = self.small.render("Autoplay",True,INK)
        self.screen.blit(label,(self.auto_rect.x+14,self.auto_rect.centery-label.get_height()//2))
        toggle = pygame.Rect(self.auto_rect.right-55,self.auto_rect.centery-11,42,22)
        pygame.draw.rect(self.screen,MELODY if self.player.autoplay else (178,183,180),toggle,border_radius=11)
        pygame.draw.circle(self.screen,PAPER,(toggle.right-11 if self.player.autoplay else toggle.x+11,toggle.centery),8)
        draw_home_button(self.screen,self.home_rect)

    def _visible_notes(self):
        track = self.player.track
        if track is None or self.player.state in {"stopped", "unavailable"}:
            return ()
        position = self.player.position_ms
        # Keep a bounded window without walking the entire score on each frame.
        if self._scan_track != self.player.index or position < self._scan_time:
            self._scan_index = 0
            self._scan_track = self.player.index
        self._scan_time = position
        while self._scan_index < len(track.notes) and track.notes[self._scan_index].end_ms < position:
            self._scan_index += 1
        visible = []
        for note in track.notes[self._scan_index:]:
            if note.start_ms > position+2800:
                break
            if note.end_ms >= position:
                visible.append(note)
        return visible

    def render(self) -> None:
        self.screen.blit(self._static,(0,0))
        track = self.player.track
        if track:
            title = self.title.render(track.title,True,INK)
            max_width = self.home_rect.left-self.field_rect.x-20
            if title.get_width() > max_width:
                scale = max_width/title.get_width()
                title = pygame.transform.smoothscale(title,(max_width,max(1,round(title.get_height()*scale))))
            self.screen.blit(title,(self.field_rect.x,31))
            progress = max(0, min(1, self.player.position_ms/track.duration_ms))
            line = pygame.Rect(self.field_rect.x,79,self.field_rect.w,4)
            pygame.draw.rect(self.screen,(225,226,215),line,border_radius=2)
            if progress:
                pygame.draw.rect(self.screen,MELODY,(line.x,line.y,max(2,int(line.w*progress)),4),border_radius=2)
        active = {}
        position = self.player.position_ms
        speed = self.field_rect.h/2800
        old_clip = self.screen.get_clip()
        self.screen.set_clip(self.field_rect)
        for note in self._visible_notes():
            key = self.keys[note.pitch]
            color = MELODY if note.voice == "melody" else HARMONY
            top = self.field_rect.bottom-(note.end_ms-position)*speed
            bottom = self.field_rect.bottom-(note.start_ms-position)*speed
            bar = pygame.Rect(key.x+max(2,key.w//10),round(top),max(3,key.w-max(4,key.w//5)),
                              max(3,round(bottom-top)-3))
            pygame.draw.rect(self.screen,color,bar,border_radius=min(7,bar.w//3))
            if note.voice == "melody":
                pygame.draw.line(self.screen,(192,229,230),(bar.x+3,bar.y+4),(bar.x+3,bar.bottom-4),2)
            if note.start_ms <= position < note.end_ms:
                active[note.pitch] = color if note.pitch not in active or note.voice == "melody" else active[note.pitch]
        self.screen.set_clip(old_clip)
        pygame.draw.rect(self.screen,INK,self.keyboard_rect.inflate(4,4),border_radius=8)
        for black in [False,True]:
            for pitch,key in self.keys.items():
                if (pitch % 12 in {1,3,6,8,10}) != black:
                    continue
                color = active.get(pitch,INK if black else PAPER)
                pygame.draw.rect(self.screen,color,key.inflate(-2,-2),border_radius=4)
                if not black and pitch % 12 == 0:
                    pygame.draw.circle(self.screen,(178,195,185),(key.centerx,key.bottom-17),3)
        pygame.draw.line(self.screen,(144,186,172),self.keyboard_rect.topleft,self.keyboard_rect.topright,4)
        self._draw_controls()

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if is_escape_chord(event) and not os.environ.get("TODDLERBOX_HEALTH_SOCKET"):
            return False
        if event.type in FOCUS_EVENTS:
            self.pointer.reset()
            return True
        if not self.pointer.accept(event):
            return True
        if is_primary_pointer_event(event,is_down=True):
            pos = pointer_event_pos(event,self.rect)
            if pos is None:
                return True
            if self.home_rect.collidepoint(pos):
                return False
            if self.pause_rect.collidepoint(pos):
                self.player.toggle_pause()
            elif self.auto_rect.collidepoint(pos):
                self.player.toggle_autoplay()
            else:
                for i,rect in enumerate(self.song_rects):
                    if rect.collidepoint(pos):
                        self.player.select(i)
                        break
        return True

    def run(self) -> None:
        try:
            self.player.select(0)
            running = True
            while running and not health.stopping():
                discard_input = False
                for event in pygame.event.get():
                    if discard_input and event.type != pygame.QUIT:
                        continue
                    if not self.handle_event(event):
                        running = False
                        break
                    if event.type in FOCUS_EVENTS:
                        discard_input = True
                if not running or health.stopping():
                    break
                self.player.update()
                self.render()
                pygame.display.flip()
                health.frame_complete()
                self.clock.tick(60)
        finally:
            self.player.close()
            self.pointer.reset()


def run_embedded(screen: pygame.Surface, screen_rect: pygame.Rect, clock: pygame.time.Clock) -> None:
    MusicApp(screen,screen_rect,clock).run()


def main() -> None:
    config = load_config()
    logger = get_runtime_logger(get_data_root(config))
    try:
        screen,rect = create_fullscreen_window()
        MusicApp(screen,rect,pygame.time.Clock(),config=config).run()
    except Exception:
        logger.exception("Music activity failed")
    finally:
        pygame.quit()
