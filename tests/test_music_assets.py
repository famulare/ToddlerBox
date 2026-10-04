"""Check the shipped, decoded collection without adding synthesis to runtime."""
from array import array
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import wave

import pytest

ASSETS = Path(__file__).resolve().parents[1] / "assets/music"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_collection_has_eighteen_complete_bounded_arrangements():
    catalog = read_json(ASSETS / "catalog.json")
    assert [t["id"] for t in catalog["tracks"]] == ["mary", "twinkle", "ode", "frere", "row", "minuet",
        "buns", "bridge", "spider", "farm", "oldman", "clock", "weasel",
        "bingo", "mulberry", "lullaby", "morning", "largo"]
    assert (catalog["keyboard_low"], catalog["keyboard_high"]) == (48, 72)
    for track in catalog["tracks"]:
        score = read_json(ASSETS / "scores" / (track["id"] + ".json"))
        assert score["schema_version"] == 1
        assert score["ticks_per_beat"] == 480
        assert 20_000 <= track["duration_ms"] <= 45_000
        transitions = []
        for note in score["notes"]:
            assert all(type(note[k]) is int for k in ("pitch", "start_tick", "duration_tick", "velocity"))
            assert 48 <= note["pitch"] <= 72
            assert note["start_tick"] >= 0 and note["duration_tick"] > 0
            assert 1 <= note["velocity"] <= 60
            transitions.extend(((note["start_tick"], 1), (note["start_tick"] + note["duration_tick"], -1)))
        active = 0
        for _, delta in sorted(transitions):
            active += delta
            assert active <= 6
        assert active == 0


@pytest.mark.parametrize("piece_id", [t["id"] for t in read_json(ASSETS / "catalog.json")["tracks"]])
def test_cues_use_exact_score_timing_and_decoded_wav_duration(piece_id):
    cues = read_json(ASSETS / (piece_id + ".json"))
    score = read_json(ASSETS / "scores" / (piece_id + ".json"))
    ms_per_tick = 60_000 / (score["tempo_bpm"] * score["ticks_per_beat"])
    source = sorted(score["notes"], key=lambda n: (n["start_tick"], n["pitch"], n["voice"]))
    assert len(source) == len(cues["notes"])
    for event, cue in zip(source, cues["notes"]):
        assert cue["pitch"] == event["pitch"] and cue["voice"] == event["voice"]
        assert cue["velocity"] == event["velocity"]
        assert cue["start_ms"] == pytest.approx(score["intro_ms"] + event["start_tick"] * ms_per_tick)
        assert cue["duration_ms"] == pytest.approx(event["duration_tick"] * ms_per_tick)
    with wave.open(str(ASSETS / (piece_id + ".wav"))) as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 22050)
        assert cues["duration_ms"] == pytest.approx(audio.getnframes() * 1000 / audio.getframerate())
        pcm = array("h", audio.readframes(audio.getnframes()))
    if sys.byteorder != "little":
        pcm.byteswap()
    intro_frames = round(cues["intro_ms"] * 22050 / 1000)
    assert max(abs(v) for v in pcm[:intro_frames]) == 0
    # The first audible attack is close to the first cue, rather than an encoder offset.
    first_onset = next(i for i, v in enumerate(pcm) if abs(v) > 32)
    assert intro_frames <= first_onset <= intro_frames + round(.05 * 22050)
    assert 1000 < max(abs(v) for v in pcm) < 32767
    assert sum(v * v for v in pcm) / len(pcm) > 100_000
    assert max(abs(v) for v in pcm[-2205:]) == 0
    end = max(n["start_ms"] + n["duration_ms"] for n in cues["notes"])
    assert cues["duration_ms"] - end == pytest.approx(cues["tail_ms"], abs=1000 / 22050)


def test_mary_uses_the_verified_familiar_reference_melody():
    # A reference fixture is preserved with its upstream MIT notice. Exclude its bass.
    fixture = (ASSETS / "sources/mary-reference.py").read_text()
    expected = [int(p) for p, velocity in re.findall(r"midi.NoteOnEvent\(tick=\d+, channel=0, data=\[(\d+), (\d+)\]\)", fixture)
                if int(velocity) > 0 and int(p) >= 60]
    score = read_json(ASSETS / "scores/mary.json")
    melody = [n["pitch"] for n in score["notes"] if n["voice"] == "melody"]
    assert len(expected) == 26
    assert melody == expected
    assert melody[:7] == [64, 62, 60, 62, 64, 64, 64]


def test_phrase_endings_and_compound_rhythm_are_preserved():
    for piece_id in ("mary", "twinkle", "ode", "frere", "row", "minuet"):
        melody = [n for n in read_json(ASSETS / "scores" / (piece_id + ".json"))["notes"] if n["voice"] == "melody"]
        assert melody[-1]["pitch"] == 60
        assert melody[-1]["duration_tick"] >= 960
    row = read_json(ASSETS / "scores/row.json")
    melody = [n for n in row["notes"] if n["voice"] == "melody"]
    assert row["meter"] == [6, 8]
    assert melody[1]["start_tick"] - melody[0]["start_tick"] == 720
    assert Counter(n["pitch"] for n in melody[:27]) == Counter(n["pitch"] for n in melody[27:])
    assert [n["start_tick"] - melody[27]["start_tick"] for n in melody[27:]] == [n["start_tick"] for n in melody[:27]]


def test_every_playback_and_instrument_asset_matches_the_pinned_hashes():
    manifest = read_json(ASSETS / "build-manifest.json")
    assert manifest["instrument_manifest_sha256"] == sha256(ASSETS / "instrument/manifest.json")
    for track in manifest["tracks"]:
        piece_id = track["id"]
        assert track["audio_sha256"] == sha256(ASSETS / (piece_id + ".wav"))
        assert track["cues_sha256"] == sha256(ASSETS / (piece_id + ".json"))
        assert track["score_sha256"] == sha256(ASSETS / "scores" / (piece_id + ".json"))
    instrument = read_json(ASSETS / "instrument/manifest.json")
    covered = set()
    for region in instrument["regions"]:
        assert region["sha256"] == sha256(ASSETS / "instrument" / region["filename"])
        assert region["source_sha256"] and instrument["revision"] in region["source_url"]
        covered.update(range(region["lokey"], region["hikey"] + 1))
    assert set(range(48, 73)) <= covered
    sources = read_json(ASSETS / "sources/manifest.json")
    for source in sources["files"]:
        assert source["sha256"] == sha256(ASSETS / source["file"])
        assert source["license"] in {"CC0-1.0", "Public Domain", "MIT", "BSD-3-Clause"}


def test_selected_instrument_zones_match_the_preserved_soft_sfz_layer():
    sfz = (ASSETS / "sources/UprightPiano.sfz").read_text()
    regions = []
    for block in sfz.split("<region>")[1:]:
        values = dict(re.findall(r"^(\w+)=([^\r\n]+)", block, flags=re.MULTILINE))
        if int(values["hivel"]) == 60:
            regions.append(values)
    instrument = read_json(ASSETS / "instrument/manifest.json")
    for selected in instrument["regions"]:
        upstream = next(r for r in regions if r["sample"] == selected["source_filename"])
        assert int(upstream["lovel"]) == 0
        assert int(upstream["volume"]) == 23
        for key in ("lokey", "hikey", "pitch_keycenter"):
            assert selected[key] == int(upstream[key])


def test_new_classical_and_jig_reference_rhythms():
    lullaby = read_json(ASSETS / "scores/lullaby.json")
    assert lullaby["meter"] == [3,4]
    assert 'mutopiacopyright = "Public Domain"' in (ASSETS / "sources/lullaby.ly").read_text()
    notes = [n for n in lullaby["notes"] if n["voice"] == "melody"]
    # Mutopia's g8 g | bes4. g8 g4 | bes4 r4 g8 bes8, transposed Eb→C.
    assert [n["pitch"] for n in notes[:8]] == [64,64,67,64,64,67,64,67]
    assert [n["duration_tick"] for n in notes[:8]] == [216,216,648,216,432,432,216,216]
    assert [n["start_tick"] for n in notes[:8]] == [0,240,480,1200,1440,1920,2880,3120]
    weasel = read_json(ASSETS / "scores/weasel.json")
    assert weasel["meter"] == [6,8]
    assert 'G2G A2A|BdB G2z' in (ASSETS / "sources/weasel.abc").read_text()
    notes = [n for n in weasel["notes"] if n["voice"] == "melody"]
    # Quarter/eighth jig pairs and the eighth rest at each phrase ending.
    assert [n["pitch"] for n in notes[:8]] == [60,60,62,62,64,67,64,60]
    assert [n["start_tick"] for n in notes[:9]] == [0,480,720,1200,1440,1680,1920,2160,2880]
    assert read_json(ASSETS / "scores/morning.json")["meter"] == [6,8]
