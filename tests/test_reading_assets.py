import array
import hashlib
import json
import math
from pathlib import Path
import runpy
import wave
from unittest.mock import Mock

import pytest

from toddlerbox.reading.catalog import Options, WORD_SETS, load_catalog

ROOT = Path(__file__).resolve().parents[1] / "assets/reading"


def test_pack_has_all_configurable_decks_and_curated_sound_units():
    words = load_catalog(ROOT, Options(word_sets=tuple(sorted(WORD_SETS))), Mock())
    assert len(words) == 75
    by_word = {card.text: card for card in words}
    assert by_word["ship"].units == ("sh", "i", "p")
    assert by_word["duck"].units == ("d", "u", "ck")
    assert by_word["frog"].units == ("f", "r", "o", "g")
    assert len(load_catalog(ROOT, Options(), Mock())) == 75
    assert len(load_catalog(ROOT, Options(word_sets=("short_a_cvc",)), Mock())) > 6
    for variant in ("sounds", "names"):
        letters = load_catalog(ROOT, Options(mode="letters", letter_audio=variant), Mock())
        assert len(letters) == 26
        assert next(c for c in letters if c.id == f"letter-q-{variant}").text == ("qu" if variant == "sounds" else "q")
    assert not any(card["kind"] == "numbers" for card in json.loads((ROOT / "catalog.json").read_text())["cards"])


def test_prepared_audio_images_and_catalog_match_checked_hashes_and_have_sources():
    outputs = json.loads((ROOT / "outputs.json").read_text())
    source_manifest = json.loads((ROOT / "sources.json").read_text())
    source_ids = {s["id"] for s in source_manifest["sources"]}
    for name, expected in outputs["sha256"].items():
        path = ROOT / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        if name != "catalog.json":
            entry = outputs["provenance"][name]
            assert entry["license"] in {"MIT", "GPL-3.0-or-later", "CC-BY-SA-3.0", "CC-BY-SA-4.0"}
            assert set(entry["sources"]) <= source_ids
        if path.suffix == ".wav":
            with wave.open(str(path), "rb") as audio:
                assert audio.getframerate() == 44100 and audio.getsampwidth() == 2 and audio.getnchannels() == 1
                assert .02 < audio.getnframes() / 44100 < 12
                data = audio.readframes(audio.getnframes())
                assert len(data) == audio.getnframes() * 2 and any(data)


def test_plum_sequence_preserves_sound_units_and_complete_whole_word_replay():
    """Check assembly integrity; this cannot establish correct pronunciation."""
    catalog = json.loads((ROOT / "catalog.json").read_text())
    card = next(card for card in catalog["cards"] if card["id"] == "word-plum")
    assert card["text"] == "plum"
    assert card["units"] == ["p", "l", "u", "m"]

    def pcm(path):
        with wave.open(str(ROOT / path), "rb") as recording:
            assert recording.getparams()[:3] == (1, 2, 44100)
            return recording.readframes(recording.getnframes())

    sequence = pcm(card["sequence"]["path"])
    replay = pcm(card["replay"]["path"])
    offset = 0
    for index, unit in enumerate(card["units"]):
        segment = pcm(f"audio/sound-{unit}.wav")
        assert sequence[offset:offset + len(segment)] == segment
        cue = card["sequence"]["cues"][index]
        assert cue["unit"] == index
        assert offset // 2 <= cue["start"] < cue["end"] <= (offset + len(segment)) // 2
        offset += len(segment)
        silence_bytes = round(44100 * (0.15 if index < 3 else 0.4)) * 2
        assert sequence[offset:offset + silence_bytes] == bytes(silence_bytes)
        offset += silence_bytes

    assert sequence[offset:] == replay
    assert len(replay) == card["replay"]["frames"] * 2
    assert len(sequence) == card["sequence"]["frames"] * 2
    replay_cue = card["replay"]["cues"][0]
    assert card["sequence"]["cues"][-1] == {
        "start": offset // 2 + replay_cue["start"],
        "end": offset // 2 + replay_cue["end"],
        "unit": -1,
    }


def test_plum_retained_sources_and_lossless_rebuild_match_approved_replay():
    manifest = json.loads((ROOT / "sources.json").read_text())
    source = next(source for source in manifest["sources"] if source["id"] == "word-plum")
    assert source["credit"] == "Dvortygirl, 2006, Wikimedia Commons; CC-BY-SA-3.0"
    assert source["license"] == "CC-BY-SA-3.0"
    for retained in (source, source["decoded_pcm"], *manifest["superseded_sources"]):
        assert hashlib.sha256((ROOT / retained["path"]).read_bytes()).hexdigest() == retained["sha256"]

    builder = runpy.run_path(str(ROOT.parents[1] / "scripts/build-reading.py"))
    data = builder["decode"](ROOT / source["decoded_pcm"]["path"])
    edit = json.loads((ROOT / "edits.json").read_text())["word-plum"]
    data = data[edit["start"]:edit["end"]]
    rms = math.sqrt(sum(float(value) ** 2 for value in data) / len(data))
    gain = min(4.0, 3000 / max(1, rms), 25000 / max(1, max(map(abs, data))))
    rebuilt = array.array("h", (round(value * gain) for value in data))
    with wave.open(str(ROOT / "audio/word-plum.wav")) as replay:
        assert builder["pcm_bytes"](rebuilt) == replay.readframes(replay.getnframes())


def test_reading_builder_rejects_changed_retained_pcm(tmp_path, monkeypatch):
    original = tmp_path / "original.ogg"
    original.write_bytes(b"synthetic original")
    (tmp_path / "decoded.wav").write_bytes(b"changed intermediate")
    (tmp_path / "sources.json").write_text(json.dumps({"sources": [{
        "id": "word-fixture", "path": original.name,
        "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "decoded_pcm": {"path": "decoded.wav", "sha256": "0" * 64},
    }]}))
    builder = runpy.run_path(str(ROOT.parents[1] / "scripts/build-reading.py"))
    builder["main"].__globals__["ASSETS"] = tmp_path
    monkeypatch.setattr("sys.argv", ["build-reading.py", "--verify"])
    with pytest.raises(ValueError, match="Decoded PCM hash changed: word-fixture"):
        builder["main"]()


@pytest.mark.parametrize("channels,width,rate", [(2, 2, 44100), (1, 1, 44100), (1, 2, 22050)])
def test_reading_builder_rejects_incompatible_lossless_pcm(tmp_path, channels, width, rate):
    path = tmp_path / "incompatible.wav"
    with wave.open(str(path), "wb") as source:
        source.setparams((channels, width, rate, 0, "NONE", "not compressed"))
        source.writeframes(bytes(100 * channels * width))
    builder = runpy.run_path(str(ROOT.parents[1] / "scripts/build-reading.py"))
    with pytest.raises(ValueError, match="PCM source must be mono 44.1kHz signed 16-bit"):
        builder["decode"](path)
