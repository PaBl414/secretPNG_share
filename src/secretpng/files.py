"""Bounded input and exclusive output publication."""

import errno
import os
import shutil
import stat
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO, Callable

from .errors import AppError, FILE_ERROR, LIMIT, OUTPUT_EXISTS

_LINK_UNSUPPORTED = {errno.EACCES, errno.EPERM, errno.ENOSYS, errno.EOPNOTSUPP, errno.EXDEV, errno.EMLINK}


def read_bounded(path: Path, limit: int) -> bytes:
    """Read a regular file without trusting its preflight size."""
    if not stat.S_ISREG(path.stat().st_mode):
        raise AppError(3, FILE_ERROR)
    with path.open("rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise AppError(3, FILE_ERROR)
        if info.st_size > limit:
            raise AppError(5, LIMIT)
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise AppError(5, LIMIT)
    return data


def check_output(path: Path) -> None:
    """Reject existing targets, including dangling symlinks."""
    if os.path.lexists(path):
        raise AppError(3, OUTPUT_EXISTS)
    if not path.parent.is_dir():
        raise AppError(3, FILE_ERROR)


def _copy_exclusive(source: Path, target: Path) -> None:
    created = False
    try:
        with target.open("xb") as output:
            created = True
            with source.open("rb") as ready:
                shutil.copyfileobj(ready, output, 65536)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise


def publish(path: Path, writer: Callable[[BinaryIO], None]) -> None:
    """Stage the result before publishing it without replacing another file."""
    check_output(path)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".secretpng-", delete=False) as stream:
            temporary = Path(stream.name)
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise
        except OSError as error:
            if error.errno not in _LINK_UNSUPPORTED and getattr(error, "winerror", None) not in (1, 50, 1314):
                raise
            _copy_exclusive(temporary, path)
    except FileExistsError as error:
        raise AppError(3, OUTPUT_EXISTS) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
