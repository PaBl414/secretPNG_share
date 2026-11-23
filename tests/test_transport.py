"""Check transfer framing on a dynamically allocated loopback port."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from secretpng.transport import receive_one, send


class TransportTests(unittest.TestCase):
    def test_loopback_transfer(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            output = Path(directory) / "received.png"
            with Image.new("RGB", (4, 4), (15, 90, 150)) as image:
                image.save(source)
            with ThreadPoolExecutor(max_workers=1) as executor:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                    listener.bind(("127.0.0.1", 0))
                    listener.listen(1)
                    port = listener.getsockname()[1]
                    future = executor.submit(receive_one, listener, output)
                    send(source, "127.0.0.1", port)
                    future.result(timeout=10)
            self.assertEqual(output.read_bytes(), source.read_bytes())
