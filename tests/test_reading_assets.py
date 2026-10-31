import hashlib
import json
from pathlib import Path
import wave
from unittest.mock import Mock

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
