"""Storage geometry for the v1 pixel layout."""

from math import isqrt
from typing import Literal

from .errors import AppError, LIMIT

Size = tuple[int, int]
Channels = Literal["L", "RGB", "RGBA"]
CHANNEL_COUNT = {"L": 1, "RGB": 3, "RGBA": 4}
MAX_FILE = 32 * 1024**2
MAX_PNG = 96 * 1024**2
MAX_SIDE = 32768
MAX_PIXELS = 16777216
BOOTSTRAP_PIXELS = 968
BODY_OVERHEAD = 1058


def ceildiv(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def valid_size(size: Size) -> bool:
    width, height = size
    return 0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE and width * height <= MAX_PIXELS


def capacity(size: Size, bpp: int, channels: Channels) -> int:
    """Return the maximum plaintext length for the current geometry."""
    width, height = size
    samples = max(0, width * height - BOOTSTRAP_PIXELS) * CHANNEL_COUNT[channels]
    return max(0, min(MAX_FILE, samples * bpp // 8 - BODY_OVERHEAD))


def required_pixels(length: int, bpp: int, channels: Channels) -> int:
    """Include the fixed bootstrap and both ciphertext tags."""
    return BOOTSTRAP_PIXELS + ceildiv(8 * (BODY_OVERHEAD + length), CHANNEL_COUNT[channels] * bpp)


def noise_size(required: int) -> Size:
    width = isqrt(required - 1) + 1
    size = width, ceildiv(required, width)
    if not valid_size(size):
        raise AppError(5, LIMIT)
    return size
