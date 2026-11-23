"""Install the project and publish a per-user launcher."""

from hashlib import sha256
from pathlib import Path
import json
import os
import platform
import shlex
import stat
import struct
import subprocess
import sys
import sysconfig
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

WINDOWS = os.name == "nt"
MARKER = "secretpng-install-v1"
LAUNCHER_MARKER = "@rem secretpng-share managed launcher"
WHEEL = "pip-25.3-py3-none-any.whl"
PACKAGE_ERROR = "Installation failed. Check network access and compatible Python wheels."
WRITE_ERROR = "Cannot install into the user directory."


class InstallError(Exception):
    """An installation failure with an actionable message."""


def _supported() -> bool:
    return (
        sys.implementation.name == "cpython"
        and (3, 10) <= sys.version_info[:2] < (3, 15)
        and struct.calcsize("P") == 8
        and platform.machine().lower() in ("amd64", "x86_64")
        and not sysconfig.get_config_var("Py_GIL_DISABLED")
    )


def _safe_directory(path: Path) -> None:
    if os.path.lexists(path):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise InstallError(WRITE_ERROR)
    else:
        path.mkdir(parents=True)


def _environment(wheel: Path | None = None) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key.upper() not in ("PYTHONHOME", "PYTHONPATH")}
    if wheel is not None:
        env["PYTHONPATH"] = str(wheel)
    return env


def _working(executable: Path, *args: str) -> bool:
    try:
        return subprocess.run(
            [str(executable), *args], env=_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    except OSError:
        return False


def _pip(executable: Path, *args: str, wheel: Path | None = None) -> None:
    subprocess.run([str(executable), "-m", "pip", "--isolated", *args], env=_environment(wheel), check=True)


def _download(url: str, host: str, limit: int) -> bytes:
    from urllib.request import urlopen

    def allowed(value: str) -> bool:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and parsed.netloc == host

    if not allowed(url):
        raise InstallError(PACKAGE_ERROR)
    with urlopen(url, timeout=30) as response:
        if not allowed(response.geturl()):
            raise InstallError(PACKAGE_ERROR)
        result = response.read(limit + 1)
    if len(result) > limit:
        raise InstallError(PACKAGE_ERROR)
    return result


def _bootstrap(executable: Path) -> None:
    document = json.loads(_download("https://pypi.org/pypi/pip/25.3/json", "pypi.org", 2 * 1024**2))
    entry = next(item for item in document["urls"] if item["filename"] == WHEEL)
    raw = _download(entry["url"], "files.pythonhosted.org", 8 * 1024**2)
    if sha256(raw).hexdigest() != entry["digests"]["sha256"]:
        raise InstallError(PACKAGE_ERROR)
    with TemporaryDirectory() as directory:
        local = Path(directory) / WHEEL
        local.write_bytes(raw)
        _pip(executable, "install", "--no-index", "--no-deps", "--ignore-installed", str(local), wheel=local)


def _launcher(app: Path, environment: Path) -> None:
    if WINDOWS:
        _safe_directory(app / "bin")
        target = app / "bin" / "secretpng.cmd"
        if os.path.lexists(target):
            if target.is_symlink() or not target.is_file():
                raise InstallError("Command path already belongs to another program.")
            with target.open("rb") as existing:
                if existing.readline(256).rstrip(b"\r\n") != LAUNCHER_MARKER.encode("ascii"):
                    raise InstallError("Command path already belongs to another program.")
        content = (
            f'{LAUNCHER_MARKER}\r\n'
            f'@"%~dp0..\\{environment.name}\\Scripts\\secretpng.exe" %*\r\n'
            '@exit /b %errorlevel%\r\n'
        ).encode("ascii")
    else:
        target = Path.home() / ".local" / "bin" / "secretpng"
        target.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(target):
            if not target.is_symlink():
                raise InstallError("Command path already belongs to another program.")
            old = target.resolve()
            if (
                old.name != "secretpng" or old.parent.name != "bin"
                or old.parent.parent.parent != app.resolve()
                or old.parents[1].name not in {f"venv-3.{minor}" for minor in range(10, 15)}
            ):
                raise InstallError("Command path already belongs to another program.")
    with TemporaryDirectory(dir=target.parent, prefix=".secretpng-") as directory:
        temporary = Path(directory) / target.name
        if WINDOWS:
            temporary.write_bytes(content)
        else:
            temporary.symlink_to(environment / "bin" / "secretpng")
        os.replace(temporary, target)


def _linux_path() -> None:
    home = Path.home()
    local_bin = home / ".local" / "bin"
    paths = os.environ.get("PATH", "").split(os.pathsep)
    if not any(entry and Path(entry).resolve() == local_bin.resolve() for entry in paths):
        profiles = [home / ".profile"]
        if (home / ".bash_profile").is_file():
            profiles.append(home / ".bash_profile")
        if Path(os.environ.get("SHELL", "")).name == "zsh":
            profiles.append(home / ".zprofile")
        marker = b"# secretpng-share PATH"
        for profile in profiles:
            existing = profile.read_bytes() if profile.exists() else b""
            if marker not in existing.splitlines():
                with profile.open("ab") as stream:
                    stream.write(b'\n# secretpng-share PATH\nexport PATH="$HOME/.local/bin:$PATH"\n')
        if Path(os.environ.get("SHELL", "")).name not in ("sh", "dash", "bash", "zsh", "ksh"):
            print(f"POSIX shells: export PATH={shlex.quote(str(local_bin))}:\"$PATH\"")


def install(repo: Path) -> None:
    """Set up the supported interpreter's venv and command entry point."""
    try:
        import ssl
        from venv import EnvBuilder
    except ImportError as error:
        raise InstallError("Install Python with venv and ssl support and retry.") from error

    root = Path(os.environ["LOCALAPPDATA"]) if WINDOWS else Path.home() / ".local" / "share"
    app = root / "secretpng-share"
    _safe_directory(app)
    lock = app / "install.lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise InstallError(f"Installation locked. Remove the lock only if no installer is running. {lock}") from error

    try:
        marker = app / MARKER
        if not marker.is_file() or marker.is_symlink():
            if any(item != lock for item in app.iterdir()):
                raise InstallError(WRITE_ERROR)
            marker.touch(exist_ok=False)
        environment = app / f"venv-{sys.version_info.major}.{sys.version_info.minor}"
        _safe_directory(environment)
        executable = environment / ("Scripts/python.exe" if WINDOWS else "bin/python")
        expected = tuple(sys.version_info[:2])
        if not _working(executable, "-I", "-c", f"import sys; assert sys.version_info[:2] == {expected} and sys.prefix != sys.base_prefix"):
            EnvBuilder(clear=False, with_pip=False).create(environment)
        try:
            if not _working(executable, "-m", "pip", "--version"):
                _bootstrap(executable)
            _pip(executable, "install", "--only-binary=:all:", "setuptools>=77,<90", "wheel>=0.45,<1")
            _pip(executable, "install", "--only-binary=:all:", "--no-build-isolation", str(repo))
        except (OSError, ValueError, KeyError, StopIteration, subprocess.CalledProcessError) as error:
            raise InstallError(PACKAGE_ERROR) from error

        _launcher(app, environment)
        if WINDOWS:
            print(f'cmd: call "{environment / "Scripts" / "activate.bat"}"')
            activate = str(environment / "Scripts" / "Activate.ps1").replace("'", "''")
            print(f"PowerShell: & '{activate}'")
        else:
            _linux_path()
            print(f"For tests: . {shlex.quote(str(environment / 'bin' / 'activate'))}")
            print("Open a new login session, then run:")
            print("secretpng --version")
    finally:
        lock.rmdir()


def main() -> int:
    if sys.argv[1:] == ["--probe"]:
        return int(not _supported())
    try:
        install(Path(sys.argv[1]).resolve())
    except InstallError as error:
        print(error, file=sys.stderr)
        return 1
    except (OSError, KeyError):
        print(WRITE_ERROR, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
