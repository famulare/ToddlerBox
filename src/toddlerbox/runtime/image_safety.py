"""Shared header/decoder limits; no global Pillow bomb-limit changes."""
import struct
import zlib

from PIL import Image

MAX_PHOTO_PIXELS = 40_000_000
# Pillow reports damaged files through several types. SyntaxError (broken PNG
# chunks) is neither OSError nor ValueError, so narrower handlers let it escape.
DECODE_ERRORS = (OSError, ValueError, SyntaxError, EOFError, struct.error, zlib.error,
                 Image.DecompressionBombError, Image.DecompressionBombWarning)
MAX_JPEG_HEADER_PIXELS = 80_000_000


def prepare_decoder(image, size=None):
    pixels = image.width * image.height
    if size is not None and getattr(image, 'format', None) in {'JPEG', 'MPO'}:
        if pixels > MAX_JPEG_HEADER_PIXELS:
            raise ValueError(f'JPEG exceeds {MAX_JPEG_HEADER_PIXELS}-pixel absolute header limit')
        if len(size) != 2 or any(type(n) is not int or n <= 0 for n in size):
            raise ValueError('Invalid image target size')
        # libjpeg selects a reduced decode before load, transpose or conversion.
        image.draft('RGB', (max(size), max(size)))
    if image.width * image.height > MAX_PHOTO_PIXELS:
        raise ValueError(f'Photo exceeds supported {MAX_PHOTO_PIXELS}-pixel limit')
