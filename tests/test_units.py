"""Unit tests for the critical v1 primitives."""

import unittest

from PIL import Image

from secretpng.capacity import capacity, required_pixels
from secretpng.crypto import seal, unseal
from secretpng.errors import AppError, BAD_PASSWORD
from secretpng.metadata import HeaderFields, crc32, pack_prefix, pack_private, parse_private, parse_public
from secretpng.padding import fit_cover, pad_edge


def fixed_header(payload_length: int) -> bytes:
    return pack_prefix(HeaderFields(
        b"SPNG", 1, 0, 2, 3, payload_length, 0, 0, 64, 64, 0,
        bytes(range(16)), bytes(range(12)), bytes(range(12, 24)),
    ))


class UnitTests(unittest.TestCase):
    def test_header(self):
        prefix = fixed_header(258)
        self.assertEqual(prefix[:16], b"SPNG\x01\x00\x02\x03" + bytes.fromhex("0000000000000102"))
        self.assertEqual(len(prefix), 73)
        wrapped = bytes(range(48))
        self.assertEqual(len(prefix + wrapped), 121)
        self.assertEqual(parse_public(prefix + wrapped).wrapped_key, wrapped)
        private = pack_private("a.tar.gz", 0x01020304)
        self.assertEqual(private, b"\x00\x08a.tar.gz" + bytes(1012) + b"\x01\x02\x03\x04")
        self.assertEqual(parse_private(private), ("a.tar.gz", 0x01020304))

    def test_crc(self):
        self.assertEqual(crc32(b"123456789"), 0xCBF43926)

    def test_padding(self):
        size = fit_cover((2, 2), 6, True)
        self.assertEqual(size, (2, 3))
        with Image.frombytes("L", (2, 2), bytes([1, 2, 3, 4])) as image:
            with pad_edge(image, size) as padded:
                self.assertEqual(padded.tobytes(), bytes([1, 2, 3, 4, 3, 4]))

    def test_encryption(self):
        data = b"\x00encrypted\xff"
        private = pack_private("sample.bin", crc32(data))
        prefix = fixed_header(len(data) + 16)
        wrapped, metadata, body = seal(b"correct", prefix, private, data)
        self.assertEqual(unseal(b"correct", prefix + wrapped, metadata, body), (private, data))
        with self.assertRaises(AppError) as caught:
            unseal(b"wrong", prefix + wrapped, metadata, body)
        self.assertEqual((caught.exception.code, str(caught.exception)), (6, BAD_PASSWORD))

    def test_capacity(self):
        self.assertEqual(capacity((64, 64), 2, "RGB"), 1288)
        self.assertLessEqual(required_pixels(1288, 2, "RGB"), 4096)
        self.assertGreater(required_pixels(1289, 2, "RGB"), 4096)
