"""Audio behavior and parent configuration safety, independent of HP speakers."""
from pathlib import Path
import subprocess
from unittest.mock import Mock
import wave
from array import array

import pygame
import pytest
import yaml

from toddlerbox.runtime.audio import apply_defaults, initialize, startup_volume
from toddlerbox.music.piano import Piano

ROOT = Path(__file__).parents[1]


@pytest.fixture
def piano(monkeypatch):
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    value = Piano({60: pygame.Rect(0, 0, 100, 100), 64: pygame.Rect(100, 0, 100, 100)}, Mock())
    yield value
    value.close()
    pygame.mixer.quit()


@pytest.mark.parametrize("finger", [False, True])
def test_release_rings_beyond_old_cutoff_and_cleanup_stops_tail(piano, finger):
    rect = pygame.Rect(0, 0, 200, 100)
    if finger:
        def event(kind):
            return pygame.event.Event(kind, x=.25, y=.5, touch_id=1, finger_id=2)
        down, up = pygame.FINGERDOWN, pygame.FINGERUP
    else:
        def event(kind):
            return pygame.event.Event(kind, pos=(50, 50), button=1, touch=False)
        down, up = pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP
    piano.event(event(down), rect)
    voice = next(iter(piano.voices.values()))[1]
    piano.event(event(up), rect)
    pygame.time.wait(160)
    piano.update()
    assert voice.get_busy() and not piano.active
    piano.close()
    assert not voice.get_busy()


@pytest.mark.parametrize("finger", [False, True])
def test_key_sustains_beyond_original_sample_then_releases_for_600ms(piano, finger):
    import time
    rect = pygame.Rect(0, 0, 200, 100)
    if finger:
        def event(kind):
            return pygame.event.Event(kind, x=.25, y=.5, touch_id=1, finger_id=2)
        down, up = pygame.FINGERDOWN, pygame.FINGERUP
    else:
        def event(kind):
            return pygame.event.Event(kind, pos=(50, 50), button=1, touch=False)
        down, up = pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP
    piano.event(event(down), rect)
    slot, voice = next(iter(piano.voices.values()))
    deadline = time.monotonic() + 2.3
    while time.monotonic() < deadline:
        piano.update()
        assert voice.get_busy()
        pygame.time.wait(20)
    assert piano.active == {60} and voice.get_queue() is not None
    piano.event(event(up), rect)
    deadline = time.monotonic() + .16
    while time.monotonic() < deadline:
        piano.update()
        pygame.time.wait(20)
    assert voice.get_busy() and not piano.active
    pygame.time.wait(500)
    piano.update()
    assert not voice.get_busy() and slot not in piano.tails


def test_missing_sustain_does_not_leave_partial_sound_cache(piano, monkeypatch):
    original = pygame.mixer.Sound
    def fail_loop(filename):
        if str(filename).endswith('-loop.wav'):
            raise pygame.error('fixture missing loop')
        return original(filename)
    monkeypatch.setattr(pygame.mixer, 'Sound', fail_loop)
    piano._play('mouse', 60)
    piano._play('mouse', 60)
    assert not piano.voices and not piano.sounds and not piano.sustains


def test_stalled_release_restarts_at_decayed_gain_without_swell(piano):
    now = [0.0]
    piano.clock = lambda: now[0]
    piano._play('key', 72)  # Short loop: an actual stall exhausts both buffers.
    slot, channel = piano.voices['key']
    piano._release('key')
    pygame.time.wait(100)
    now[0] = .1
    piano.update()
    previous = channel.get_volume()
    pygame.time.wait(350)
    now[0] = .45
    assert not channel.get_busy()
    played_at = []
    class Probe:
        def __getattr__(self, name):
            return getattr(channel, name)
        def play(self, *args):
            played_at.append(channel.get_volume())
            return channel.play(*args)
    piano.channels[slot] = Probe()
    piano.update()
    assert len(played_at) == 1 and played_at[0] < .10
    assert channel.get_volume() <= previous


def test_drained_held_voices_still_reserve_shared_gain(piano):
    piano._play('a', 60)
    piano._play('b', 64)
    for channel in piano.channels.values():
        piano._stop_channel(channel)
    assert not any(channel.get_busy() for channel in piano.channels.values())
    reserved = piano._reserve_gain()
    assert reserved <= .70 / 3
    assert reserved + sum(piano.gains.values()) <= .70 + 1e-9


def test_sustain_pcm_is_verified_bounded_and_has_continuous_wraps():
    import hashlib, json, math
    root = ROOT / 'assets/music/keys/sustain'
    manifest = json.loads((root / 'manifest.json').read_text())
    assert set(manifest['files']) == {f'{pitch}-{kind}.wav' for pitch in range(48,73)
                                      for kind in ('attack', 'loop')}
    for filename, metadata in manifest['files'].items():
        path = root / filename
        assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata['sha256']
        with wave.open(str(path)) as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (22050, 1, 2)
            samples = array('h', wav.readframes(wav.getnframes()))
        assert 0 < len(samples) < 22050 and max(abs(v) for v in samples) <= 16384
        if filename.endswith('-loop.wav'):
            rms = math.sqrt(sum(v*v for v in samples)/len(samples))/32768
            assert .055 < rms <= .141
            # The loop boundary is an original positive-going zero crossing,
            # not a jump back to the note's percussive beginning.
            steps = max(abs(b-a) for a,b in zip(samples, samples[1:]))
            assert abs(samples[0]-samples[-1]) <= steps


def test_glissando_and_repeated_note_keep_previous_release_channels(piano):
    piano._play("mouse", 60)
    first = piano.voices["mouse"][0]
    piano._play("mouse", 64)
    second = piano.voices["mouse"][0]
    assert first != second and piano.channels[first].get_busy()
    piano._play("mouse", 64)
    assert piano.voices["mouse"][0] not in {first, second}
    assert all(piano.channels[slot].get_busy() for slot in (first, second))


def test_eight_held_voices_are_not_stolen_and_oldest_tail_is_reused(piano):
    for i in range(8):
        piano._play(i, 60)
    held = {token: voice[0] for token, voice in piano.voices.items()}
    piano._play("ninth", 64)
    assert "ninth" not in piano.voices
    assert sum(channel.get_volume() for channel in piano.channels.values()) <= .70
    piano._release(2)
    piano._release(4)
    piano._play("next", 64)
    assert piano.voices["next"][0] == held[2]
    assert all(piano.voices[i][0] == held[i] for i in (0, 1, 3, 5, 6, 7))
    assert len(piano.channels) == 8


def test_tail_finishes_and_update_reclaims_its_slot(piano):
    piano._play(1, 60)
    piano._release(1)
    pygame.time.wait(680)
    piano.update()
    assert not piano.tails
    assert not any(channel.get_busy() for channel in piano.channels.values())


def test_overlapping_release_envelopes_never_undo_shared_headroom(piano):
    for i in range(8):
        piano._play(i, 60)
        piano._release(i)
        pygame.time.wait(10)
        piano.update()
        assert sum(channel.get_volume() for channel in piano.channels.values()
                   if channel.get_busy()) <= .70
    for _ in range(8):
        pygame.time.wait(40)
        piano.update()
        assert sum(channel.get_volume() for channel in piano.channels.values()
                   if channel.get_busy()) <= .70


def test_pinned_assets_leave_headroom_for_louder_song_and_all_keys():
    def peak(path):
        with wave.open(str(path)) as source:
            assert source.getsampwidth() == 2
            samples = array("h", source.readframes(source.getnframes()))
        return max(abs(sample) for sample in samples) / 32768
    # The actual library uses the catalog's paths, not a guessed folder layout.
    from toddlerbox.music.library import load_library
    tracks, _, _ = load_library(ROOT / "assets/music", Mock())
    assert len(tracks) == 18
    song_peak = max(peak(track.audio) for track in tracks)
    key_peak = max(peak(path) for path in (ROOT / "assets/music/keys").glob("*.wav"))
    assert song_peak <= .65 and key_peak <= .5
    assert song_peak + key_peak * .70 < 1.0


@pytest.mark.parametrize("value,expected", [(None,.8),(True,.8),(float("nan"),.8),
                                             (-1,0),(5,1),(.4,.4),(10**400,1),(-10**400,0)])
def test_startup_volume_is_finite_bounded_and_parent_configurable(value, expected):
    assert startup_volume({"audio": {"startup_volume": value}}) == expected


def test_startup_waits_for_sink_then_sets_volume_before_unmuting():
    now, calls = [0.0], []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return Mock(returncode=int(len(calls) == 1))
    assert initialize({"audio": {"startup_volume": .6}}, clock=lambda:now[0],
                      sleep=lambda seconds:now.__setitem__(0,now[0]+seconds), run=run)
    assert [args[1] for args, _ in calls] == ["set-volume", "set-volume", "set-mute"]
    assert calls[1][0][-1] == "0.6" and calls[2][0][-1] == "0"
    assert all(0 < kwargs["timeout"] <= .4 for _, kwargs in calls)


def test_stalled_audio_device_is_bounded_without_unmuting():
    now, calls = [0.0], []
    def run(args, **kwargs):
        calls.append(args)
        now[0] += kwargs["timeout"]
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])
    assert not initialize({}, clock=lambda:now[0],
                          sleep=lambda seconds:now.__setitem__(0,now[0]+seconds), run=run)
    assert now[0] <= 1.51 and all(args[1] == "set-volume" for args in calls)


@pytest.fixture
def parent_config(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "system"))
    monkeypatch.setattr("os.geteuid", lambda: 0)
    for name in ("etc/toddlerbox", "run/toddlerbox-system", "var/lib/toddlerbox-system"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "run/toddlerbox-system/mode").write_text("parent")
    path = tmp_path / "etc/toddlerbox/config.yaml"
    path.write_text(yaml.safe_dump({"data_root":"/private-work", "music":{"volume":.12,"autoplay":False},
                                   "reading":{"volume":.2,"letter_case":"uppercase"}}))
    return tmp_path, path


def test_parent_opt_in_is_repeatable_preserves_other_settings_and_first_backup(parent_config):
    root, path = parent_config
    original = path.read_bytes()
    apply_defaults(root)
    first = path.read_bytes()
    apply_defaults(root)
    assert path.read_bytes() == first
    result = yaml.safe_load(first)
    assert result["music"] == {"volume":1.0,"autoplay":False}
    assert result["reading"] == {"volume":.7,"letter_case":"uppercase"}
    assert result["data_root"] == "/private-work"
    assert (root / "var/lib/toddlerbox-system/audio-config-before.yaml").read_bytes() == original


def test_audio_opt_in_does_not_modify_unrelated_aliased_settings(parent_config):
    root, path = parent_config
    path.write_text("music: &shared\n  volume: 0.1\nreading: *shared\nother: *shared\n")
    apply_defaults(root)
    result = yaml.safe_load(path.read_bytes())
    assert result["music"]["volume"] == 1.0
    assert result["reading"]["volume"] == .70
    assert result["other"]["volume"] == .1


@pytest.mark.parametrize("unsafe", ["child", "symlink", "hardlink", "malformed"])
def test_audio_defaults_refuse_unsafe_paths_or_child_mode(parent_config, unsafe):
    root, path = parent_config
    if unsafe == "child":
        (root / "run/toddlerbox-system/mode").write_text("child")
    elif unsafe in {"symlink", "hardlink"}:
        target = root / "untouched.yaml"
        path.rename(target)
        if unsafe == "symlink":
            path.symlink_to(target)
        else:
            path.hardlink_to(target)
    else:
        path.write_text("music: []\n")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        apply_defaults(root)
    assert path.read_bytes() == before
    assert not (root / "var/lib/toddlerbox-system/audio-config-before.yaml").exists()


def test_loading_existing_gains_does_not_silently_migrate_parent_choices(tmp_path, monkeypatch):
    from toddlerbox.config import load_config
    path = tmp_path / "config.yaml"
    path.write_text("music:\n  volume: 0.25\nreading:\n  volume: 0.35\nmath:\n  volume: 0.35\n")
    monkeypatch.setenv("KIDBOX_CONFIG", str(path))
    value = load_config()
    assert [value[name]["volume"] for name in ("music", "reading", "math")] == [.25,.35,.35]
