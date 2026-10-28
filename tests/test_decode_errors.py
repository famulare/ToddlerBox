"""Pillow's SyntaxError for damaged PNG chunks is isolated like any decode error."""
import io
import json
import shutil
import struct
import sys
import zlib
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1]))
from sync_fixtures import MemoryDrive, package, paths, png
from system.tbx_sync.install import setup
from system.tbx_sync.media import validate_photo
from system.tbx_sync.worker import Run
from toddlerbox.photos.app import _prepare_thumbnail
from toddlerbox.reading.catalog import Options, load_catalog

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "reading"


def broken_chunk(data: bytes) -> bytes:
    """Split IDAT in two and give the second an invalid chunk type (valid CRC)."""
    out, position = [data[:8]], 8
    while position < len(data):
        length, = struct.unpack(">I", data[position:position + 4])
        kind = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        position += 12 + length
        parts = [body[:len(body) // 2], body[len(body) // 2:]] if kind == b"IDAT" else [body]
        for index, part in enumerate(parts):
            chunk_kind = b"\x00\x01\x02\x03" if kind == b"IDAT" and index == 1 else kind
            out.append(struct.pack(">I", len(part)) + chunk_kind + part
                       + struct.pack(">I", zlib.crc32(chunk_kind + part) & 0xFFFFFFFF))
    return b"".join(out)


def detailed_png(size=(200, 160)):
    image = Image.new("RGB", size, (20, 160, 40))
    for x in range(size[0]):
        image.putpixel((x, x % size[1]), (x % 256, 0, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_pillow_raises_syntax_error_for_this_damage():
    with pytest.raises(SyntaxError):
        Image.open(io.BytesIO(broken_chunk(detailed_png()))).load()


def test_sync_validation_reports_damage_as_value_error():
    with pytest.raises(ValueError):
        validate_photo(broken_chunk(detailed_png()), "damaged.png")


def test_damaged_drive_photo_is_an_issue_and_creations_still_upload(tmp_path):
    locations = paths(tmp_path)
    archive, digest = package(tmp_path)
    setup(locations, archive, digest, minimum=0)
    (locations.data / "paint/latest.png").write_bytes(png("blue"))
    drive = MemoryDrive()
    drive.files["Photos/damaged.png"] = broken_chunk(detailed_png())
    drive.files["Photos/fine.png"] = png("red")
    status = Run(locations, factory=drive, save=lambda: "ok", minimum=0).execute()
    assert status["state"] == "partial"
    assert "photo-invalid-or-unpublishable" in status["issues"]
    assert (locations.library / "fine.png").exists() and not (locations.library / "damaged.png").exists()
    assert any(name.startswith("Creations/") and name.endswith("paint/latest.png") for name in drive.files)


def test_reading_card_with_damaged_picture_is_skipped_not_fatal(tmp_path):
    catalog = json.loads((ASSETS / "catalog.json").read_text())
    first, second = catalog["cards"][0], catalog["cards"][1]
    for card in (first, second):
        for relative in [card["image"], card["sequence"]["path"], card["replay"]["path"]]:
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ASSETS / relative, target)
    catalog["cards"] = [first, second]
    (tmp_path / "catalog.json").write_text(json.dumps(catalog))
    picture = tmp_path / first["image"]
    picture.write_bytes(broken_chunk(picture.read_bytes()))
    assert [c.id for c in load_catalog(tmp_path, Options(), Mock())] == [second["id"]]


def test_damaged_cached_thumbnail_is_regenerated_from_the_photo(tmp_path):
    photo = tmp_path / "library/photo.png"
    photo.parent.mkdir()
    photo.write_bytes(detailed_png())
    thumb = tmp_path / "thumbs/photo_png.png"
    thumb.parent.mkdir()
    thumb.write_bytes(broken_chunk(detailed_png((64, 48))))
    pixels, size = _prepare_thumbnail(photo, thumb, (100, 100))
    assert size == (100, 80)
    Image.open(thumb).load()
