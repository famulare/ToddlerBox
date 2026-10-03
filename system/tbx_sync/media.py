from __future__ import annotations

import io
import json
import warnings
from PIL import Image

# Image assembly installs this exact shared module beside the root-owned worker.
try:
    from .image_safety import prepare_decoder
except ImportError:
    from toddlerbox.runtime.image_safety import prepare_decoder


def validate_photo(data, name):
    suffix = name.rsplit('.', 1)[-1].lower()
    expected = {'jpg':'JPEG', 'jpeg':'JPEG', 'png':'PNG'}.get(suffix)
    if expected is None:
        raise ValueError('Only JPG, JPEG and PNG are supported for sync')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ({'JPEG','MPO'} if expected=='JPEG' else {'PNG'}):
                    raise ValueError('Image format does not match its name')
                if expected=='PNG' and getattr(image,'n_frames',1)!=1:
                    raise ValueError('Animated PNG is not supported')
                # JPEG-compatible MPO gain-map containers use their primary frame
                # exactly as Photos does; preserve all original bytes on disk.
                prepare_decoder(image, (1920, 1920))
                image.load()  # Strict decoder: do not enable LOAD_TRUNCATED_IMAGES.
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ValueError('Image exceeds safe decoding limits') from exc


def typing_text(data):
    if len(data) > 8*1024**2:
        raise ValueError('Typing document too large')
    record = json.loads(data)
    if not isinstance(record, dict) or record.get('version') != 1:
        raise ValueError('Unsupported Typing document version')
    lines = record.get('rich_lines')
    if not isinstance(lines, list) or not 1 <= len(lines) <= 10000:
        raise ValueError('Invalid Typing lines')
    output = []
    total = 0
    for line in lines:
        if not isinstance(line, list):
            raise ValueError('Invalid Typing line')
        chars = []
        for glyph in line:
            if (not isinstance(glyph, dict) or not isinstance(glyph.get('char'), str)
                    or len(glyph['char']) != 1 or type(glyph.get('size')) is not int
                    or not 1 <= glyph['size'] <= 1000
                    or glyph.get('style') not in {'plain', 'bold', 'italic'}):
                raise ValueError('Invalid Typing glyph')
            chars.append(glyph['char'])
        total += len(chars)
        if total > 100000:
            raise ValueError('Typing document too long')
        output.append(''.join(chars))
    return ('\n'.join(output) + '\n').encode('utf-8')
