"""Command-line entry point for secretPNG_share."""

import argparse
import getpass
from importlib.metadata import version
from io import UnsupportedOperation
from ipaddress import IPv4Address
from pathlib import Path
import sys
import warnings

from .capacity import CHANNEL_COUNT, MAX_PNG, capacity
from .codec import decode, encode
from .errors import AppError, FILE_ERROR, INVALID_ARGS, LIMIT, PASSWORD_REQUIRED
from .files import read_bounded
from .png_io import load_png
from .transport import DEFAULT_PORT, receive, send


class Parser(argparse.ArgumentParser):
    """Keep diagnostics from echoing potentially secret argument values."""

    def error(self, message: str) -> None:
        raise AppError(2, INVALID_ARGS)


def _carrier_options(parser: Parser) -> None:
    parser.add_argument(
        "--bpp", type=int, choices=(1, 2, 3, 4), default=2,
        help="Bits stored per channel sample (default: 2). Higher values increase capacity and can change the cover more visibly.",
    )
    parser.add_argument(
        "--channels", choices=tuple(CHANNEL_COUNT), default="RGB",
        help="PNG channels (default: RGB). L is grayscale, RGB discards transparency, and RGBA uses alpha for storage too.",
    )


def _encode_options(parser: Parser) -> None:
    parser.add_argument("--input", type=Path, required=True, metavar="FILE", help="File to encrypt and hide.")
    parser.add_argument(
        "--output", type=Path, default=Path("sealed.png"), metavar="PNG",
        help="New PNG to write (default: sealed.png in the current directory).",
    )
    parser.add_argument(
        "--password", metavar="TEXT",
        help="Encryption password. Omit to enter and confirm it privately. An explicit value may be visible in shell history or process listings.",
    )
    _carrier_options(parser)


def _parser() -> Parser:
    parser = Parser(
        prog="secretpng", allow_abbrev=False, formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Hide password-encrypted files inside PNG pixels and transfer PNGs over a local network.",
        epilog=(
            "Quick start:\n"
            "  secretpng encode --input example.xyz --mode cover --cover example.png\n"
            "  secretpng decode --input sealed.png --output recovered.xyz\n"
            "\n"
            "Use 'secretpng COMMAND --help' for command options. Existing output files are never overwritten."
        ),
    )
    parser.add_argument("--version", action="version", version=f"secretpng {version('secretpng-share')}")
    commands = parser.add_subparsers(title="commands", dest="command", metavar="COMMAND", required=True)

    def command(name: str, summary: str, description: str, *examples: str) -> Parser:
        return commands.add_parser(
            name, help=summary, description=description, allow_abbrev=False,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="Examples:\n" + "\n".join(f"  secretpng {name} {example}" for example in examples),
        )

    encoder = command(
        "encode", "Encrypt and hide a file in a new PNG.",
        "Encrypt a file and its original name, then save a new PNG. "
        "Input files may be empty. The size limit is 32 MiB, subject to image capacity.",
        "--input example.xyz",
        "--input example.xyz --mode cover --cover example.png --output sealed.png",
    )
    _encode_options(encoder)
    encoder.add_argument(
        "--mode", choices=("noise", "cover"), default="noise",
        help="Generate a random image (noise, default) or embed in a supplied image (cover).",
    )
    encoder.add_argument(
        "--cover", type=Path, metavar="PNG",
        help="Static PNG with up to 8 bits per sample. Required in cover mode.",
    )
    padding = encoder.add_mutually_exclusive_group()
    padding.add_argument(
        "--pad-fill", choices=("edge",),
        help="Cover only. Expand a small image by repeating its edge pixels (default).",
    )
    padding.add_argument(
        "--no-pad", action="store_true",
        help="Cover only. Fail if the image has insufficient capacity at its current size.",
    )

    creator = command(
        "create", "Generate a PNG sized for an encrypted file.",
        "Create a PNG from scratch and allocate enough pixels for the encrypted file and its original name. "
        "Recover it with extract or decode.",
        "--input example.xyz --output generated.png",
    )
    _encode_options(creator)

    decoder = command(
        "decode", "Recover the original file from a secretPNG image.",
        "Recover and verify an encrypted file. Image settings are detected automatically.",
        "--input sealed.png",
        "--input sealed.png --output recovered.xyz",
    )
    extractor = command(
        "extract", "Extract a file from a generated or cover PNG.",
        "Recover and verify the encrypted file from a PNG made by create or encode.",
        "--input generated.png",
    )
    for reader in (decoder, extractor):
        reader.add_argument("--input", type=Path, required=True, metavar="PNG", help="PNG created by secretpng create or encode.")
        reader.add_argument(
            "--output", type=Path, metavar="FILE",
            help="New file to write. By default, restore the original filename in the current directory. "
                 "Specify a path if that name is occupied or unsupported.",
        )
        reader.add_argument(
            "--password", metavar="TEXT",
            help="Same password used to encode the file. Omit for a private prompt. "
                 "An explicit value may be visible in shell history or process listings.",
        )

    measure = command(
        "capacity", "Print the maximum file size a cover can hold.",
        "Print the maximum plaintext size in bytes for the selected settings and current image dimensions. "
        "A result of 0 means there is no room for a nonempty file.",
        "--cover example.png --channels RGB --bpp 2",
    )
    measure.add_argument("--cover", type=Path, required=True, metavar="PNG", help="Static PNG with up to 8 bits per sample.")
    _carrier_options(measure)

    sender = command(
        "send", "Send one PNG to a LAN receiver.",
        "Send a static PNG over TCP and check delivery. Start the receiver first and use the same port on both sides.",
        "--input sealed.png --host 192.168.1.20",
    )
    sender.add_argument("--input", type=Path, required=True, metavar="PNG", help="PNG file to send (up to 96 MiB).")
    sender.add_argument("--host", required=True, metavar="IPV4", help="Receiver's LAN IPv4 address.")

    receiver = command(
        "receive", "Listen for and save one PNG over LAN.",
        "Wait for one TCP transfer, check its SHA-256 digest, and save the PNG. "
        "Use a trusted LAN and share the decoding password separately.",
        "--host 192.168.1.20 --output received.png",
    )
    receiver.add_argument("--output", type=Path, required=True, metavar="PNG", help="New PNG to write after verification.")
    receiver.add_argument(
        "--host", default="0.0.0.0", metavar="IPV4",
        help="Local IPv4 address to listen on (default: 0.0.0.0, all IPv4 interfaces).",
    )
    for endpoint in (sender, receiver):
        endpoint.add_argument(
            "--port", type=int, default=DEFAULT_PORT, metavar="PORT",
            help=f"TCP port, 1-65535 (default: {DEFAULT_PORT}).",
        )
    return parser


def _password(value: str | None, confirm: bool) -> bytes:
    try:
        if value is None:
            if not sys.stdin.isatty():
                raise AppError(2, PASSWORD_REQUIRED)
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = getpass.getpass("Password: ")
                if confirm and value != getpass.getpass("Confirm password: "):
                    raise AppError(2, PASSWORD_REQUIRED)
        raw = value.encode("utf-8", errors="strict")
    except (EOFError, UnicodeError, getpass.GetPassWarning) as error:
        raise AppError(2, PASSWORD_REQUIRED) from error
    if not 1 <= len(raw) <= 1024:
        raise AppError(2, PASSWORD_REQUIRED)
    return raw


def _address(options: argparse.Namespace) -> str:
    try:
        address = IPv4Address(options.host)
    except ValueError as error:
        raise AppError(2, INVALID_ARGS) from error
    if not 1 <= options.port <= 65535 or address.is_multicast or int(address) == 0xFFFFFFFF:
        raise AppError(2, INVALID_ARGS)
    if options.command == "send" and address.is_unspecified:
        raise AppError(2, INVALID_ARGS)
    return str(address)


def _dispatch(options: argparse.Namespace) -> None:
    command = options.command
    if command in ("encode", "create", "receive") and options.output.suffix.lower() != ".png":
        raise AppError(2, INVALID_ARGS)

    if command == "encode":
        cover_mode = options.mode == "cover"
        if cover_mode != (options.cover is not None) or (
            not cover_mode and (options.pad_fill is not None or options.no_pad)
        ):
            raise AppError(2, INVALID_ARGS)
        encode(
            options.input, options.output, options.mode, options.cover, options.bpp,
            options.channels, not options.no_pad, _password(options.password, confirm=True),
        )
        print(options.output)
    elif command == "create":
        encode(
            options.input, options.output, "noise", None, options.bpp,
            options.channels, True, _password(options.password, confirm=True),
        )
        print(options.output)
    elif command in ("decode", "extract"):
        print(decode(options.input, options.output, _password(options.password, confirm=False)))
    elif command == "capacity":
        with load_png(read_bounded(options.cover, MAX_PNG), options.channels, encoded=False) as image:
            print(capacity(image.size, options.bpp, options.channels))
    elif command == "send":
        send(options.input, _address(options), options.port)
        print("Transfer complete.")
    else:
        receive(options.output, _address(options), options.port)
        print(options.output)


def main(argv: list[str] | None = None) -> int:
    """Parse one command and report its documented exit status."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="backslashreplace" if stream is not sys.stdin else "strict")
            except UnsupportedOperation:
                pass
    try:
        _dispatch(_parser().parse_args(argv))
        return 0
    except AppError as error:
        code, message = error.code, str(error)
    except KeyboardInterrupt:
        code, message = 130, "Cancelled."
    except MemoryError:
        code, message = 5, LIMIT
    except OSError:
        code, message = 3, FILE_ERROR
    except Exception:
        code, message = 1, "Unexpected application error."
    print(message, file=sys.stderr)
    return code
