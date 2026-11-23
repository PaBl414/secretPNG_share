"""Validate static PNG inputs and write clean PNG carriers."""

from io import BytesIO
from struct import unpack_from
from typing import BinaryIO
import warnings
import zlib

from PIL import Image

from .capacity import Channels, MAX_PNG, valid_size
from .errors import AppError, INVALID_PNG, LIMIT

SIGNATURE = b"\x89PNG\r\n\x1a\n"
ENCODED_MODES = {0: "L", 2: "RGB", 6: "RGBA"}


def _inspect(raw: bytes) -> tuple[int, int, bool]:
    if len(raw) > MAX_PNG:
        raise AppError(5, LIMIT)
    if len(raw) < 33 or not raw.startswith(SIGNATURE):
        raise AppError(4, INVALID_PNG)
    if raw[8:16] != b"\x00\x00\x00\x0dIHDR":
        raise AppError(4, INVALID_PNG)
    width, height, depth, color = unpack_from(">IIBB", raw, 16)
    if not width or not height or depth > 8:
        raise AppError(4, INVALID_PNG)
    if not valid_size((width, height)):
        raise AppError(5, LIMIT)

    view = memoryview(raw)
    position = 8
    transparency = False
    seen_data = False
    while position + 12 <= len(raw):
        length = unpack_from(">I", view, position)[0]
        kind = raw[position + 4:position + 8]
        end = position + 8 + length
        if end + 4 > len(raw) or kind == b"acTL" or (kind == b"IHDR" and position != 8):
            break
        if zlib.crc32(view[position + 4:end]) != unpack_from(">I", view, end)[0]:
            break
        if kind == b"tRNS":
            transparency = True
        if kind == b"IDAT":
            seen_data = True
        if kind == b"IEND":
            if length == 0 and seen_data and end + 4 == len(raw):
                return depth, color, transparency
            break
        position = end + 4
    raise AppError(4, INVALID_PNG)


def load_png(raw: bytes, channels: Channels | None, encoded: bool) -> Image.Image:
    """Open a bounded PNG snapshot and optionally convert a cover."""
    depth, color, transparency = _inspect(raw)
    if encoded and (depth != 8 or color not in ENCODED_MODES or transparency):
        raise AppError(4, INVALID_PNG)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw), formats=["PNG"]) as image:
                image.verify()
            with Image.open(BytesIO(raw), formats=["PNG"]) as image:
                image.load()
                if encoded and image.mode != ENCODED_MODES[color]:
                    raise AppError(4, INVALID_PNG)
                if channels is None:
                    return image.copy()
                if image.mode == "P" and transparency:
                    with image.convert("RGBA") as expanded:
                        return expanded.convert(channels)
                return image.convert(channels)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise AppError(5, LIMIT) from error
    except (OSError, SyntaxError, ValueError, OverflowError, EOFError, zlib.error) as error:
        raise AppError(4, INVALID_PNG) from error


def save_png(image: Image.Image, stream: BinaryIO) -> None:
    """Write pixels as PNG without copying ancillary image metadata."""
    with Image.frombytes(image.mode, image.size, image.tobytes()) as clean:
        clean.save(stream, format="PNG", compress_level=6, optimize=False)
    if stream.tell() > MAX_PNG:
        raise AppError(5, LIMIT)
