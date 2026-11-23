"""Binary SPNG v1 header representation."""

from dataclasses import astuple, dataclass
from struct import Struct
from zlib import crc32 as _crc32

from .errors import AppError, INVALID_CONTAINER, NO_HEADER

MAGIC = b"SPNG"
VERSION = 1
PREFIX = Struct(">4sBBBBQIIIIB16s12s12s")
PUBLIC_SIZE = PREFIX.size + 48
PRIVATE = Struct(">H1020sI")
PRIVATE_CIPHERTEXT_SIZE = PRIVATE.size + 16


@dataclass(frozen=True)
class HeaderFields:
    magic: bytes
    version: int
    mode: int
    bpp: int
    channels: int
    payload_length: int
    original_width: int
    original_height: int
    width: int
    height: int
    padded: int
    salt: bytes
    wrap_nonce: bytes
    data_nonce: bytes


@dataclass(frozen=True)
class PublicHeader(HeaderFields):
    wrapped_key: bytes


def pack_prefix(fields: HeaderFields) -> bytes:
    """Serialize the authenticated public prefix."""
    return PREFIX.pack(*astuple(fields))


def parse_public(raw: bytes) -> PublicHeader:
    """Validate format markers and unpack the remaining public fields."""
    if len(raw) != PUBLIC_SIZE or raw[:4] != MAGIC:
        raise AppError(4, NO_HEADER)
    if raw[4] != VERSION:
        raise AppError(4, "Unsupported secretPNG version.")
    return PublicHeader(*PREFIX.unpack_from(raw), raw[PREFIX.size:])


def pack_private(name: str, crc: int) -> bytes:
    """Serialize the name and CRC before encryption."""
    encoded = name.encode("utf-8", errors="strict")
    if not 1 <= len(encoded) <= 1020 or b"\0" in encoded:
        raise ValueError("Invalid source filename.")
    return PRIVATE.pack(len(encoded), encoded, crc)


def parse_private(raw: bytes) -> tuple[str, int]:
    """Reject noncanonical name fields before returning metadata."""
    if len(raw) != PRIVATE.size:
        raise AppError(4, INVALID_CONTAINER)
    length, field, crc = PRIVATE.unpack(raw)
    if not 1 <= length <= 1020 or any(field[length:]) or b"\0" in field[:length]:
        raise AppError(4, INVALID_CONTAINER)
    try:
        return field[:length].decode("utf-8", errors="strict"), crc
    except UnicodeError as error:
        raise AppError(4, INVALID_CONTAINER) from error


def crc32(data: bytes) -> int:
    return _crc32(data) & 0xFFFFFFFF
