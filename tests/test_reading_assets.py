import hashlib
import json
from pathlib import Path
import wave
from unittest.mock import Mock

from toddlerbox.reading.catalog import Options, WORD_SETS, load_catalog

ROOT = Path(__file__).resolve().parents[1] / "assets/reading"


def test_pack_has_all_configurable_decks_and_curated_sound_units():
    words = load_catalog(ROOT, Options(word_sets=tuple(sorted(WORD_SETS))), Mock())
    assert len(words) == 30
    by_word = {card.text: card for card in words}
    assert by_word["ship"].units == ("sh", "i", "p")
    assert by_word["duck"].units == ("d", "u", "ck")
    assert by_word["frog"].units == ("f", "r", "o", "g")
    assert len(load_catalog(ROOT, Options(), Mock())) == 6
    for variant in ("sounds", "names"):
        letters = load_catalog(ROOT, Options(mode="letters", letter_audio=variant), Mock())
        assert len(letters) == 26
        assert next(c for c in letters if c.id == f"letter-q-{variant}").text == ("qu" if variant == "sounds" else "q")
    numbers = load_catalog(ROOT, Options(mode="numbers", number_max=30), Mock())
    assert [c.number for c in numbers] == list(range(31))


def test_prepared_audio_images_and_catalog_match_checked_hashes_and_have_sources():
    outputs = json.loads((ROOT / "outputs.json").read_text())
    source_manifest = json.loads((ROOT / "sources.json").read_text())
    numbers = json.loads((ROOT / "sources/numbers-provenance.json").read_text())
    source_ids = {s["id"] for s in source_manifest["sources"]} | {s["id"] for s in numbers["clips"]}
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
