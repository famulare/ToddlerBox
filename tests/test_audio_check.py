import io
import struct
import subprocess
import wave

from toddlerbox.runtime import audio_check


def test_speaker_tone_is_bounded_stereo_and_fades():
    with wave.open(io.BytesIO(audio_check.tone())) as stream:
        assert (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getnframes()) == (2, 2, 44100, 44100)
        raw = stream.readframes(stream.getnframes())
    values = struct.unpack('<' + 'h' * (len(raw) // 2), raw)
    assert max(map(abs, values)) <= 1639
    assert values[::2] == values[1::2]
    assert values[:2] == values[-2:] == (0, 0)


def test_diagnostics_are_explicit_image_packages():
    from pathlib import Path
    packages = (Path(__file__).parents[1] / 'system/packages.txt').read_text().splitlines()
    assert 'alsa-utils' in packages and 'pulseaudio-utils' in packages


def test_parent_audio_check_uses_bounded_player_and_cleans_up(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(audio_check.os, 'geteuid', lambda: 1000)
    monkeypatch.delenv('TODDLERBOX_APP_CONTROL', raising=False)
    monkeypatch.setattr('builtins.input', lambda prompt: '')
    seen = []
    def play(args, **kwargs):
        path = Path(args[1])
        assert args[0] == '/usr/bin/pw-play' and path.read_bytes() == audio_check.tone()
        assert kwargs == {'check': True, 'timeout': 5}
        seen.append(path)
    monkeypatch.setattr(audio_check.subprocess, 'run', play)
    assert audio_check.main() == 0
    assert len(seen) == 1 and not seen[0].parent.exists()


def test_failed_or_stalled_player_still_cleans_up(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(audio_check.os, 'geteuid', lambda: 1000)
    monkeypatch.delenv('TODDLERBOX_APP_CONTROL', raising=False)
    monkeypatch.setattr('builtins.input', lambda prompt: '')
    seen = []
    def play(args, **kwargs):
        seen.append(Path(args[1]))
        raise subprocess.TimeoutExpired(args, 5)
    monkeypatch.setattr(audio_check.subprocess, 'run', play)
    assert audio_check.main() == 1
    assert not seen[0].parent.exists()
