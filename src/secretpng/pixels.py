"""Row-major bit storage with an independently readable bootstrap."""

from PIL import Image

from .capacity import BOOTSTRAP_PIXELS, CHANNEL_COUNT
from .errors import AppError, INVALID_CONTAINER, NO_HEADER
from .metadata import PUBLIC_SIZE


def embed(image: Image.Image, public: bytes, body: bytes, bpp: int) -> Image.Image:
    """Store header and body without modifying unused samples."""
    channels = CHANNEL_COUNT[image.mode]
    pixels = bytearray(image.tobytes())
    mask = (1 << bpp) - 1
    if len(public) != PUBLIC_SIZE or len(pixels) < BOOTSTRAP_PIXELS * channels:
        raise AppError(4, INVALID_CONTAINER)
    for index in range(BOOTSTRAP_PIXELS):
        offset = index * channels
        bit = (public[index // 8] >> (7 - index % 8)) & 1
        pixels[offset] = (pixels[offset] & 254) | bit

    offset = BOOTSTRAP_PIXELS * channels
    if len(body) * 8 > (len(pixels) - offset) * bpp:
        raise AppError(4, INVALID_CONTAINER)
    accumulator = bit_count = 0
    for value in body:
        accumulator = (accumulator << 8) | value
        bit_count += 8
        while bit_count >= bpp:
            bit_count -= bpp
            pixels[offset] = (pixels[offset] & (255 ^ mask)) | (accumulator >> bit_count)
            accumulator &= (1 << bit_count) - 1
            offset += 1
    if bit_count:
        pixels[offset] = (pixels[offset] & (255 ^ mask)) | (accumulator << (bpp - bit_count))
    return Image.frombytes(image.mode, image.size, bytes(pixels))


def read_public(image: Image.Image) -> bytes:
    """Read one bit per pixel regardless of the encoded body settings."""
    width, height = image.size
    if width * height < BOOTSTRAP_PIXELS:
        raise AppError(4, NO_HEADER)
    samples = image.load()
    result = bytearray(PUBLIC_SIZE)
    for index in range(BOOTSTRAP_PIXELS):
        sample = samples[index % width, index // width]
        first = sample if image.mode == "L" else sample[0]
        result[index // 8] |= (first & 1) << (7 - index % 8)
    return bytes(result)


def read_body(image: Image.Image, bpp: int, count: int) -> bytes:
    """Read the declared byte count and ignore trailing sample bits."""
    pixels = image.tobytes()
    offset = BOOTSTRAP_PIXELS * CHANNEL_COUNT[image.mode]
    if count * 8 > (len(pixels) - offset) * bpp:
        raise AppError(4, INVALID_CONTAINER)
    result = bytearray(count)
    accumulator = bit_count = written = 0
    mask = (1 << bpp) - 1
    while written < count:
        accumulator = (accumulator << bpp) | (pixels[offset] & mask)
        offset += 1
        bit_count += bpp
        if bit_count >= 8:
            bit_count -= 8
            result[written] = accumulator >> bit_count
            accumulator &= (1 << bit_count) - 1
            written += 1
    return bytes(result)
