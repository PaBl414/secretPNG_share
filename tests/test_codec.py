"""Exercise CLI round trips and cover capacity errors."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from secretpng.cli import main


class CodecTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enter_directory())
        self.stdout = StringIO()
        self.stderr = StringIO()

    def enter_directory(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return directory.name

    def invoke(self, *arguments):
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            return main([str(argument) for argument in arguments])

    def test_noise_round_trip(self):
        original = self.root / "żółć.bin"
        original.write_bytes(b"")
        carrier = self.root / "noise.png"
        self.assertEqual(self.invoke(
            "create", "--input", original, "--output", carrier,
            "--channels", "L", "--bpp", 3, "--password", "demo",
        ), 0, self.stderr.getvalue())
        recovered = self.root / "recovered"
        recovered.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(recovered)
            self.assertEqual(self.invoke("extract", "--input", carrier, "--password", "demo"), 0, self.stderr.getvalue())
        finally:
            os.chdir(previous)
        self.assertEqual([file.name for file in recovered.iterdir()], [original.name])
        self.assertEqual((recovered / original.name).read_bytes(), original.read_bytes())

    def test_cover_round_trip(self):
        original, cover, carrier, recovered = (self.root / name for name in (
            "source.bin", "cover.png", "sealed.png", "recovered.bin",
        ))
        data = bytes(range(256)) * 3
        original.write_bytes(data)
        with Image.new("RGBA", (12, 12), (100, 65, 200, 255)) as image:
            image.save(cover)
        self.assertEqual(self.invoke(
            "encode", "--mode", "cover", "--cover", cover, "--input", original, "--output", carrier,
            "--channels", "RGBA", "--bpp", 3, "--password", "demo",
        ), 0, self.stderr.getvalue())
        with Image.open(carrier) as image:
            self.assertGreater(image.width * image.height, 144)
        self.assertEqual(self.invoke(
            "decode", "--input", carrier, "--output", recovered, "--password", "demo",
        ), 0, self.stderr.getvalue())
        self.assertEqual(recovered.read_bytes(), data)

    def test_cover_too_small(self):
        source, cover, output = (self.root / name for name in ("source.bin", "cover.png", "sealed.png"))
        source.write_bytes(b"data")
        with Image.new("RGB", (1, 1)) as image:
            image.save(cover)
        self.assertEqual(self.invoke(
            "encode", "--mode", "cover", "--input", source, "--cover", cover,
            "--output", output, "--no-pad", "--password", "demo",
        ), 5)
        self.assertEqual(self.stderr.getvalue().strip(), "Cover is too small with --no-pad.")
        self.assertFalse(output.exists())
