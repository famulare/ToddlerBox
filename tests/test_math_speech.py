import hashlib
import json
from pathlib import Path
import struct
from unittest.mock import Mock
import wave

import pygame
import pytest

from toddlerbox.math.model import MODES, Options, options_from_config
from toddlerbox.math.speech import NumberBank, NumberPlayer, ROOT
from toddlerbox.reading.catalog import RATE, Speech
from toddlerbox.reading.playback import SpeechDeviceError
from test_math import app, pixels, select, tap


def test_three_modes_and_previous_trial_configuration_remains_readable():
    assert MODES == ("numbers", "addition", "subtraction")
    for mode in ("numerals", "count"):
        original = {"math": {"mode": mode}}
        assert options_from_config(original, Mock()).mode == "numbers"
        assert original["math"]["mode"] == mode


@pytest.mark.parametrize("value,expected", [(True, .35), (float("nan"), .35),
                                            (float("inf"), .35), (10**400, 1), (-10**400, 0), (-1, 0), (2, 1), (.6, .6)])
def test_parent_volume_is_finite_bounded(value, expected):
    assert options_from_config({"math": {"volume": value}}, Mock()).volume == expected


def test_every_bundled_number_is_complete_bounded_pcm_with_exact_hash():
    bank = NumberBank(Mock())
    assert set(bank.entries) == set(range(101))
    for number in range(101):
        clip = bank.get(number)
        assert clip and 1000 <= clip.frames <= RATE*6
        with wave.open(str(clip.path), "rb") as source:
            samples = struct.unpack('<'+'h'*clip.frames, source.readframes(clip.frames))
            peak = max(abs(s) for s in samples)
            assert 1000 < peak < 32767
    assert len(bank.cache) == 101
    assert bank.get(100) is bank.cache[100]
    assert bank.get(True) is None and bank.get(101) is None
    assert bank.entries[100]["text"] == "one hundred"
    assert bank.entries[42]["text"] == "forty two"


def synthetic_bank(root):
    path = root/"number-7.wav"
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        stream.writeframes(b'\x00\x00'*RATE)
    row = {"number": 7, "frames": RATE, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    catalog = {"schema_version": 1, "sample_rate": RATE, "clips": [row]}
    (root/"catalog.json").write_text(json.dumps(catalog))
    return path, row, catalog


@pytest.mark.parametrize("damage", ["changed", "truncated", "symlink", "oversize", "format", "frames", "duplicate"])
def test_damaged_or_escaping_recordings_are_quietly_isolated(tmp_path, damage):
    path, row, catalog = synthetic_bank(tmp_path)
    if damage == "changed":
        path.write_bytes(path.read_bytes()[:-1]+b'\x01')
    elif damage == "truncated":
        path.write_bytes(path.read_bytes()[:-10])
        row['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif damage == "symlink":
        other = tmp_path/'elsewhere.wav'
        path.rename(other)
        path.symlink_to(other)
    elif damage == "oversize":
        path.write_bytes(b'\x00'*600001)
    elif damage == "format":
        with wave.open(str(path), 'wb') as stream:
            stream.setparams((2, 2, RATE, 0, "NONE", "not compressed"))
            stream.writeframes(b'\x00'*RATE*4)
        row['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif damage == "frames":
        row['frames'] = RATE*7
    else:
        catalog['clips'].append(dict(row))
    (tmp_path/'catalog.json').write_text(json.dumps(catalog))
    assert NumberBank(Mock(), tmp_path).get(7) is None


def test_playback_is_explicit_interruptible_bounded_and_device_failure_retryable():
    audio, bank = Mock(), Mock()
    bank.get.return_value = Speech(Path('number.wav'), RATE, ())
    now = [0.0]
    player = NumberPlayer(Mock(), audio=audio, bank=bank, clock=lambda: now[0])
    audio.play.assert_not_called()
    player.play(7)
    player.play(8)
    assert audio.play.call_count == 2 and audio.stop.call_count == 2
    audio.busy.return_value = True
    now[0] = 2.1
    player.update()
    assert player.deadline is None and audio.stop.call_count == 3
    audio.play.side_effect = SpeechDeviceError
    player.play(9)
    assert player.deadline is None
    audio.play.side_effect = None
    player.play(9)
    assert player.deadline is not None
    bank.get.return_value = None
    player.play(100)
    assert player.deadline is None


def test_number_reveal_is_silent_objects_stay_and_only_disclosed_number_can_speak(app):
    app.player = Mock()
    select(app, "numbers", 23)
    app.render()
    before = pixels(app, app.body_rect)
    assert app._target(app.speech_rect.center) is None
    tap(app, app.speech_rect.center)
    app.player.play.assert_not_called()
    tap(app, app.question_rect.center)
    app.render()
    assert pixels(app, app.body_rect) == before
    app.player.play.assert_not_called()
    tap(app, app.speech_rect.center)
    app.player.play.assert_called_once_with(23)
    tap(app, app.next_rect.center)
    assert not app.revealed and app.player.cancel.called
    for mode, a, b, result in (("addition", 8, 7, 15), ("subtraction", 23, 8, 15)):
        select(app, mode, a, b, revealed=True)
        tap(app, app.speech_rect.center)
        app.player.play.assert_called_with(result)
    tap(app, app.mode_rect.center)
    app.player.cancel.assert_called()
    app.player.reset_mock()
    app.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
    app.player.cancel.assert_called_once()
    app.player.reset_mock()
    assert not tap(app, app.home_rect.center)
    app.player.cancel.assert_called_once()


def test_real_sdl_clip_and_home_cleanup(app):
    select(app, 'numbers', 42, revealed=True)
    tap(app, app.speech_rect.center)
    assert pygame.mixer.music.get_busy()
    assert app.player.deadline is not None
    assert not tap(app, app.home_rect.center)
    assert not pygame.mixer.music.get_busy() and app.player.deadline is None


def test_speaker_is_visible_only_after_reveal_and_stays_clear_of_other_controls(app):
    select(app, 'numbers', 7)
    app.render()
    before = pixels(app, app.speech_rect)
    app.reveal()
    app.render()
    assert pixels(app, app.speech_rect) != before
    assert app.rect.contains(app.speech_rect)
    assert all(not app.speech_rect.colliderect(r) for r in (app.home_rect, app.mode_rect, app.question_rect))
