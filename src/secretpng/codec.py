"""Compose image storage, authentication, and safe file output."""

from pathlib import Path
from secrets import token_bytes
from typing import Literal

from PIL import Image

from .capacity import CHANNEL_COUNT, MAX_FILE, MAX_PNG, Channels, noise_size, required_pixels, valid_size
from .crypto import seal, unseal
from .errors import AppError, INTEGRITY, INVALID_CONTAINER, LIMIT
from .files import check_output, publish, read_bounded
from .metadata import (
    MAGIC, PRIVATE_CIPHERTEXT_SIZE, VERSION, HeaderFields, PublicHeader, crc32,
    pack_prefix, pack_private, parse_private, parse_public,
)
from .padding import fit_cover, pad_edge
from .pixels import embed, read_body, read_public
from .png_io import load_png, save_png

Mode = Literal["noise", "cover"]
_CHANNELS_BY_COUNT = {count: mode for mode, count in CHANNEL_COUNT.items()}
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    prefix + digit for prefix in ("COM", "LPT") for digit in "123456789¹²³"
}


def _portable_name(name: str) -> bool:
    return (
        bool(name)
        and name not in (".", "..")
        and all(ord(char) >= 32 and char not in '<>:"/\\|?*' for char in name)
        and not name.endswith((" ", "."))
        and len(name.encode("utf-8")) <= 255
        and len(name.encode("utf-16-le")) <= 510
        and name.split(".", 1)[0].rstrip(" ").upper() not in _RESERVED
    )


def encode(
    source: Path, output: Path, mode: Mode, cover: Path | None, bpp: int,
    channels: Channels, allow_pad: bool, password: bytes,
) -> None:
    """Encrypt a file and write it into a noise or cover image."""
    check_output(output)
    data = read_bounded(source, MAX_FILE)
    try:
        private = pack_private(source.name, crc32(data))
    except ValueError as error:
        raise AppError(5, LIMIT) from error
    required = required_pixels(len(data), bpp, channels)
    if cover is None:
        size = noise_size(required)
        base = Image.frombytes(channels, size, token_bytes(size[0] * size[1] * CHANNEL_COUNT[channels]))
        original = (0, 0)
        padded = 0
    else:
        with load_png(read_bounded(cover, MAX_PNG), channels, encoded=False) as image:
            original = image.size
            size = fit_cover(original, required, allow_pad)
            base = image.copy() if size == original else pad_edge(image, size)
        padded = int(size != original)

    with base:
        fields = HeaderFields(
            MAGIC, VERSION, int(mode == "cover"), bpp, CHANNEL_COUNT[channels],
            len(data) + 16, *original, *size, padded,
            token_bytes(16), token_bytes(12), token_bytes(12),
        )
        prefix = pack_prefix(fields)
        wrapped, private_ct, body_ct = seal(password, prefix, private, data)
        del data
        carrier = embed(base, prefix + wrapped, private_ct + body_ct, bpp)
    with carrier:
        publish(output, lambda stream: save_png(carrier, stream))


def _validate(header: PublicHeader, image: Image.Image) -> int:
    channels = _CHANNELS_BY_COUNT.get(header.channels)
    length = header.payload_length - 16
    if (
        header.mode not in (0, 1) or header.padded not in (0, 1)
        or not 1 <= header.bpp <= 4 or channels != image.mode
        or not 0 <= length <= MAX_FILE
        or image.size != (header.width, header.height)
    ):
        raise AppError(4, INVALID_CONTAINER)
    required = required_pixels(length, header.bpp, channels)
    original = (header.original_width, header.original_height)
    if required > header.width * header.height:
        raise AppError(4, INVALID_CONTAINER)
    try:
        if header.mode == 0:
            valid = original == (0, 0) and header.padded == 0 and noise_size(required) == image.size
        else:
            valid = (
                valid_size(original)
                and fit_cover(original, required, True) == image.size
                and header.padded == int(original != image.size)
            )
    except AppError as error:
        raise AppError(4, INVALID_CONTAINER) from error
    if not valid:
        raise AppError(4, INVALID_CONTAINER)
    return length


def decode(source: Path, output: Path | None, password: bytes) -> Path:
    """Recover an authenticated file and return its output path."""
    with load_png(read_bounded(source, MAX_PNG), None, encoded=True) as image:
        public = read_public(image)
        header = parse_public(public)
        length = _validate(header, image)
        body = read_body(image, header.bpp, PRIVATE_CIPHERTEXT_SIZE + header.payload_length)
    private, data = unseal(password, public, body[:PRIVATE_CIPHERTEXT_SIZE], body[PRIVATE_CIPHERTEXT_SIZE:])
    name, checksum = parse_private(private)
    if len(data) != length:
        raise AppError(4, INVALID_CONTAINER)
    if crc32(data) != checksum:
        raise AppError(6, INTEGRITY)
    if output is None:
        if not _portable_name(name):
            raise AppError(3, "Unsafe filename. Specify --output.")
        output = Path(name)
    publish(output, lambda stream: stream.write(data))
    return output
