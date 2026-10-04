from pathlib import Path
from unittest.mock import Mock
import json

import pygame
import pytest

from toddlerbox.music.app import MusicApp
from toddlerbox.music.library import load_library
from test_music import Audio


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    monkeypatch.setenv('SDL_AUDIODRIVER', 'dummy')
    pygame.init()
    screen = pygame.display.set_mode((800,600))
    value = MusicApp(screen,screen.get_rect(),pygame.time.Clock(), config={'data_root':str(tmp_path)},audio=Audio())
    yield value
    value.player.close(); value.piano.close()
    pygame.quit()


def finger(app, kind, pos, id=1):
    return app.handle_event(pygame.event.Event(kind,x=pos[0]/app.rect.w,y=pos[1]/app.rect.h,finger_id=id,touch_id=1))


def tap(app, pos):
    finger(app,pygame.FINGERDOWN,pos)
    return finger(app,pygame.FINGERUP,pos)


def test_swipe_browses_without_selecting_or_changing_song(app):
    app.player.select(0)
    before = app.player.audio.started.copy()
    start = app.song_rects[1].center
    finger(app,pygame.FINGERDOWN,start)
    finger(app,pygame.FINGERMOTION,(start[0],start[1]-100))
    finger(app,pygame.FINGERUP,(start[0],start[1]-100))
    assert app.rail_offset == 100
    assert app.player.audio.started == before
    app._scroll(100000)
    assert app.song_rects[-1].bottom == app.song_list_rect.bottom
    last=app.song_rects[-1].center
    tap(app,last)
    assert app.player.index == 17
    app.render()
    assert app.song_list_rect.contains(app.song_rects[-1])
    app._scroll(-100000)
    assert app.rail_offset == 0


def test_wheel_is_scoped_and_clipped_rows_cannot_cover_pinned_controls(app):
    app.handle_event(pygame.event.Event(pygame.MOUSEWHEEL,y=-3,pos=app.keyboard_rect.center))
    assert app.rail_offset == 0
    app.handle_event(pygame.event.Event(pygame.MOUSEWHEEL,y=-3,pos=app.song_list_rect.center))
    assert app.rail_offset == 198
    app.render()
    before = pygame.image.tobytes(app.screen.subsurface(app.keyboard_rect),'RGB')
    assert app._target(app.free_rect.center) == ('free',None)
    tap(app,app.free_rect.center)
    assert app.free_play and app.player.state == 'stopped'
    assert app.free_rect.h >= 48
    app.render()
    assert pygame.image.tobytes(app.screen.subsurface(app.keyboard_rect),'RGB') == before


def test_focus_and_second_finger_do_not_leave_a_stale_selection(app):
    start=app.song_rects[1].center
    finger(app,pygame.FINGERDOWN,start)
    finger(app,pygame.FINGERMOTION,(start[0],start[1]-100),id=2)
    assert app.rail_offset == 0
    app.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
    finger(app,pygame.FINGERUP,start)
    assert not app.player.audio.started and app.pressed is None


@pytest.mark.parametrize('action',['pause','auto','song'])
def test_rail_controls_preserve_independent_held_piano_fingers(app,action):
    app.player.select(0)
    piano=app.keys[60].center
    finger(app,pygame.FINGERDOWN,piano,id=2)
    assert app.piano.pointers
    pos={'pause':app.pause_rect.center,'auto':app.auto_rect.center,'song':app.song_rects[1].center}[action]
    tap(app,pos)
    assert app.piano.pointers and 60 in app.piano.active
    finger(app,pygame.FINGERUP,piano,id=2)
    assert not app.piano.pointers


def test_bounded_collection_accepts_18_and_rejects_unbounded_catalog(app,tmp_path):
    assert len(app.player.tracks)==18
    root=Path(__file__).resolve().parents[1]/'assets/music'
    catalog=json.loads((root/'catalog.json').read_text())
    catalog['tracks']*=2
    (tmp_path/'catalog.json').write_text(json.dumps(catalog))
    assert load_library(tmp_path,Mock())[0]==[]
