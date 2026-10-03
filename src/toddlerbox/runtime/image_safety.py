"""Shared header/decoder limits; no global Pillow bomb-limit changes."""
MAX_PHOTO_PIXELS = 40_000_000
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
