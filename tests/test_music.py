import json
from pathlib import Path
from unittest.mock import Mock

import pygame
import pytest

from toddlerbox.music.library import Track, load_library
from toddlerbox.music.playback import MusicPlayer
from toddlerbox.music.visuals import piano_keys


class Audio:
    def __init__(self):
        self.pos = 0
        self.playing = False
        self.fail = set()
        self.started = []
        self.stopped = 0

    def play(self, track, volume):
        self.started.append((track.id, volume))
        if track.id in self.fail:
            raise pygame.error("Missing audio device or damaged track")
        self.pos = 0
        self.playing = True

    def position(self):
        return self.pos

    def busy(self):
        return self.playing

    def pause(self):
        self.playing = False

    def resume(self):
        self.playing = True

    def stop(self):
        self.stopped += 1
        self.playing = False


@pytest.fixture
def player():
    tracks = [Track(str(i),f"Song {i}",Path(f"{i}.wav"),10_000,()) for i in range(3)]
    audio = Audio()
    now = [0.0]
    music = MusicPlayer(tracks,Mock(),audio=audio,clock=lambda:now[0])
    return music,audio,now


def test_pause_freezes_visual_clock_and_does_not_trigger_autoplay(player):
    music,audio,now = player
    music.select(0)
    audio.pos = 2500
    music.toggle_pause()
    audio.pos = 20_000  # Mixer/backend may report a different clock through suspension.
    now[0] = 20
    music.update()
    assert music.position_ms == 2500
    assert music.index == 0 and music.state == "paused"
    music.toggle_pause()
    audio.pos += 100
    music.update()
    assert music.position_ms == 2600


def test_manual_selection_cancels_pending_completion(player):
    music,audio,now = player
    music.select(0)
    audio.pos = 9990
    audio.playing = False
    music.update()
    assert music.state == "gap"
    music.select(2)
    now[0] += 10
    music.update()
    assert music.index == 2 and music.state == "playing"
    assert audio.started == [("0",1.0),("2",1.0)]


def test_bad_playlist_is_attempted_once_then_stops_until_manual_retry(player):
    music,audio,now = player
    audio.fail = {"0","1","2"}
    music.select(0)
    for _ in range(20):
        now[0] += 1
        music.update()
    assert len(audio.started) == 3
    assert music.state == "unavailable"
    audio.fail.clear()
    music.toggle_pause()
    assert music.state == "playing"
    assert music.failed == set()


def test_autoplay_wrap_and_off_during_gap(player):
    music,audio,now = player
    music.select(2)
    audio.pos, audio.playing = 9990, False
    music.update()
    now[0] = 1
    music.update()
    assert music.index == 0 and music.state == "playing"
    audio.pos, audio.playing = 9990, False
    music.update()
    music.toggle_autoplay()
    now[0] = 50
    music.update()
    assert music.index == 0 and music.state == "finished"


def test_audio_failure_during_position_read_remains_quiet_and_close_stops(player):
    music,audio,now = player
    music.select(0)
    audio.position = Mock(side_effect=pygame.error("Device lost"))
    music.update()
    assert music.state == "unavailable" and not audio.playing
    music.close()
    assert music.state == "stopped" and not audio.playing


def test_latency_offset_and_no_backward_visual_jump(player):
    music,audio,now = player
    music.latency_ms = 40
    music.select(0)
    audio.pos = 500
    music.update()
    assert music.position_ms == 460
    audio.pos = 495
    music.update()
    assert music.position_ms == 460


@pytest.mark.parametrize("value",[float("nan"),float("inf"),None,"invalid",True])
def test_invalid_settings_use_valid_defaults(value):
    music = MusicPlayer([],Mock(),volume=value,latency_ms=value)
    assert music.volume == 1.0
    assert music.latency_ms == 0


def test_black_keys_align_between_their_white_neighbors():
    keys = piano_keys(pygame.Rect(100,400,750,150),48,72)
    assert len(keys) == 25
    for pitch in [49,51,54,56,58,61,63,66,68,70]:
        assert keys[pitch].centerx == pytest.approx(keys[pitch-1].right,abs=1)
        assert keys[pitch].height < keys[pitch-1].height
    assert keys[48].left == 100
    assert keys[72].right == 850


def test_catalog_quarantines_bad_track_without_changing_other_song_identity(tmp_path):
    (tmp_path/"catalog.json").write_text(json.dumps({"schema_version":1,"keyboard_low":48,"keyboard_high":72,
        "tracks":[{"id":"bad","title":"Bad","audio":"bad.wav","cues":"bad.json"},
                  {"id":"ode","title":"Ode","audio":"ode.wav","cues":"ode.json"}]}))
    (tmp_path/"bad.json").write_text("{")
    (tmp_path/"ode.json").write_text(json.dumps({"schema_version":1,"id":"ode","duration_ms":4000,
        "notes":[{"pitch":64,"start_ms":1500,"duration_ms":500,"voice":"melody"}]}))
    tracks,low,high = load_library(tmp_path,Mock())
    assert [track.id for track in tracks] == ["ode"]
    assert (low,high) == (48,72)


@pytest.mark.parametrize("size",[(1024,600),(1366,768)])
def test_music_layout_touch_and_cleanup(tmp_path,monkeypatch,size):
    monkeypatch.setenv("SDL_VIDEODRIVER","dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER","dummy")
    pygame.init()
    from toddlerbox.music.app import MusicApp
    screen = pygame.display.set_mode(size)
    audio = Audio()
    app = MusicApp(screen,screen.get_rect(),pygame.time.Clock(),config={"data_root":str(tmp_path)},audio=audio)
    assert len(app.player.tracks) == 18
    controls = [r.clip(app.song_list_rect) for r in app.song_rects if r.colliderect(app.song_list_rect)] + [app.free_rect,app.pause_rect,app.auto_rect,app.home_rect]
    for i,rect in enumerate(controls):
        assert screen.get_rect().contains(rect)
        assert all(not rect.colliderect(other) for other in controls[i+1:])
        assert not rect.colliderect(app.keyboard_rect)
    center = app.song_rects[1].center
    finger = pygame.event.Event(pygame.FINGERDOWN,x=center[0]/size[0],y=center[1]/size[1],finger_id=1,touch_id=1)
    mouse = pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=center,button=1,touch=True)
    app.handle_event(finger)
    app.handle_event(mouse)
    app.handle_event(pygame.event.Event(pygame.FINGERUP,x=center[0]/size[0],y=center[1]/size[1],finger_id=1,touch_id=1))
    assert len(audio.started) == 1
    app.render()
    # A Home event exits run and the finally path releases the stream.
    pygame.event.clear()
    app.pointer.reset()
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=app.home_rect.center,button=1,touch=False))
    app.run()
    assert not audio.playing and app.player.state == "stopped"
    pygame.quit()


def test_embedded_exception_also_releases_audio(tmp_path,monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER","dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER","dummy")
    pygame.init()
    from toddlerbox.music.app import MusicApp
    screen = pygame.display.set_mode((1024,600))
    audio = Audio()
    app = MusicApp(screen,screen.get_rect(),pygame.time.Clock(),config={"data_root":str(tmp_path)},audio=audio)
    app.render = Mock(side_effect=RuntimeError("drawing failed"))
    pygame.event.clear()
    with pytest.raises(RuntimeError):
        app.run()
    assert not audio.playing and app.player.state == "stopped"
    pygame.quit()


def test_focus_change_discards_already_fetched_pointer_input(tmp_path,monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER","dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER","dummy")
    pygame.init()
    from toddlerbox.music.app import MusicApp
    screen = pygame.display.set_mode((1024,600))
    audio = Audio()
    app = MusicApp(screen,screen.get_rect(),pygame.time.Clock(),config={"data_root":str(tmp_path)},audio=audio)
    stale = pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=app.song_rects[1].center,button=1,touch=False)
    events = Mock(side_effect=[[pygame.event.Event(pygame.WINDOWFOCUSGAINED),stale],
                              [pygame.event.Event(pygame.QUIT)]])
    monkeypatch.setattr(pygame.event,"get",events)
    app.run()
    assert [item[0] for item in audio.started] == ["mary"]
    assert not audio.playing
    pygame.quit()
