"""Single-image TCP transfers over IPv4."""

from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
import socket
from struct import Struct
import sys
from time import monotonic

from .capacity import MAX_PNG
from .errors import AppError, NETWORK_ERROR, REJECTED
from .files import check_output, publish, read_bounded
from .png_io import load_png

FRAME = Struct(">4sBQ32s")
MAGIC = b"SPNT"
VERSION = 1
DEFAULT_PORT = 47831
BLOCK_SIZE = 65536


def _timeout(connection: socket.socket, deadline: float) -> None:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError
    connection.settimeout(min(30.0, remaining))


def _recv(connection: socket.socket, count: int, deadline: float) -> bytes:
    _timeout(connection, deadline)
    return connection.recv(count)


def _recv_exact(connection: socket.socket, count: int, deadline: float) -> bytes:
    result = bytearray()
    while len(result) < count:
        block = _recv(connection, count - len(result), deadline)
        if not block:
            raise AppError(7, REJECTED)
        result.extend(block)
    return bytes(result)


def _send(connection: socket.socket, data: bytes | memoryview, deadline: float) -> None:
    _timeout(connection, deadline)
    connection.sendall(data)


def send(source: Path, host: str, port: int) -> None:
    """Send an immutable PNG snapshot and require a committed ACK."""
    raw = read_bounded(source, MAX_PNG)
    load_png(raw, None, encoded=False).close()
    header = FRAME.pack(MAGIC, VERSION, len(raw), sha256(raw).digest())
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(10)
            connection.connect((host, port))
            deadline = monotonic() + 300
            _send(connection, header, deadline)
            view = memoryview(raw)
            for offset in range(0, len(raw), BLOCK_SIZE):
                _send(connection, view[offset:offset + BLOCK_SIZE], deadline)
            _timeout(connection, deadline)
            connection.shutdown(socket.SHUT_WR)
            if _recv(connection, 1, deadline) != b"\x00":
                raise AppError(7, REJECTED)
    except OSError as error:
        raise AppError(7, NETWORK_ERROR) from error


def _receive_frame(connection: socket.socket, deadline: float) -> bytearray:
    magic, version, size, expected = FRAME.unpack(_recv_exact(connection, FRAME.size, deadline))
    if magic != MAGIC or version != VERSION or not 1 <= size <= MAX_PNG:
        raise AppError(7, REJECTED)
    body = bytearray()
    digest = sha256()
    while len(body) < size:
        block = _recv(connection, min(size - len(body), BLOCK_SIZE), deadline)
        if not block:
            raise AppError(7, REJECTED)
        digest.update(block)
        body.extend(block)
    if _recv(connection, 1, deadline) or not compare_digest(digest.digest(), expected):
        raise AppError(7, REJECTED)
    return body


def receive_one(listener: socket.socket, output: Path) -> None:
    """Accept one connection on an already listening IPv4 socket."""
    try:
        listener.settimeout(120)
        connection, _ = listener.accept()
    except OSError as error:
        raise AppError(7, NETWORK_ERROR) from error
    with connection:
        deadline = monotonic() + 300
        try:
            try:
                raw = _receive_frame(connection, deadline)
            except OSError as error:
                raise AppError(7, NETWORK_ERROR) from error
            load_png(bytes(raw), None, encoded=False).close()
            _timeout(connection, deadline)
            publish(output, lambda stream: stream.write(raw))
        except BaseException:
            try:
                _send(connection, b"\x01", deadline)
            except OSError:
                pass
            raise
        try:
            _send(connection, b"\x00", deadline)
        except OSError as error:
            raise AppError(7, NETWORK_ERROR) from error


def receive(output: Path, host: str, port: int) -> None:
    """Listen for a single transfer on the requested interface."""
    check_output(output)
    try:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError as error:
        raise AppError(7, NETWORK_ERROR) from error
    with listener:
        try:
            listener.bind((host, port))
            listener.listen(1)
        except OSError as error:
            raise AppError(7, NETWORK_ERROR) from error
        print(f"Listening on {host}:{port}", file=sys.stderr, flush=True)
        receive_one(listener, output)
