# secretPNG_share

Encrypt a file, including its filename, inside a PNG. Decoding restores the original bytes. Use a generated noise image or embed into a static PNG cover. Cover pixels can change, and the cover can grow by edge replication.

The plaintext limit is 32 MiB, subject to pixel capacity. PNG files are limited to 96 MiB, 16,777,216 pixels, and 32,768 pixels per side. Static PNG covers up to 8 bits per sample are supported, including palette and transparency. RGB and L output discard alpha.

## Installation

Use standard x64 CPython 3.10–3.14 with venv and TLS support. Linux requires glibc 2.28 or newer. The installer downloads ready-made wheels from PyPI into a user venv. Run from the repository root.

Linux:

```sh
sh ./install.sh
```

Windows, from cmd or PowerShell:

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

Open a new login session after installation and run `secretpng --version`.

## Usage

### Create a PNG and recover its file

```text
secretpng create --input example.xyz --output generated.png
secretpng extract --input generated.png --output recovered.xyz
```

`create` generates the pixels and computes the dimensions needed for the encrypted contents and filename. It defaults to `sealed.png` when `--output` is omitted. Enter the same password for both commands.

Without `--output`, `extract` restores the original filename in the current directory. Existing files are never overwritten. Use an explicit output path if the original filename is already taken. Both `extract` and `decode` can recover files from PNGs made by `create` or `encode`.

### Use an existing PNG as a cover

```text
secretpng capacity --cover photo.png --channels RGB --bpp 2
secretpng encode --mode cover --cover photo.png --input report.pdf --output sealed.png
secretpng decode --input sealed.png --output recovered.pdf
```

RGB and 2 bits per channel are the defaults. If the cover is too small, the encoder extends its edges. Use `--no-pad` to require the original dimensions. Use `secretpng COMMAND --help` for each command's options.


## Format v1

Public header, unsigned big-endian, 121 bytes:

| Offset | Bytes | Field |
|---:|---:|---|
|0|4|ASCII SPNG|
|4|1|Version 1|
|5|1|Mode, 0 noise or 1 cover|
|6|1|Bits per sample, 1–4|
|7|1|Channel count, 1/3/4|
|8|8|Encrypted file length including the tag|
|16|8|Original cover width and height, zero for noise|
|24|8|Output width and height|
|32|1|Padding flag|
|33|16|PBKDF2 salt|
|49|12|Key-wrap nonce|
|61|12|Base data nonce|
|73|48|Wrapped AES key and tag|

Private header before encryption:

| Offset | Bytes | Field |
|---:|---:|---|
|0|2|Filename length in UTF-8 bytes|
|2|1020|Filename including extension, followed by zero padding|
|1022|4|CRC32 of the original file|

The public header uses the first channel's lowest bit in the first 968 pixels. The remaining row-major pixels hold the 1,042-byte encrypted private header followed by the encrypted file, MSB-first across L, RGB, or RGBA samples.

## LAN

Run the receiver first, then run the sender on the other computer:

```text
secretpng receive --host 192.168.1.20 --output received.png
secretpng send --host 192.168.1.20 --input sealed.png
```

 Use the receiver's LAN IPv4 address and the same TCP port on both computers. Default port is 47831. For a collision, choose an available port with `--port` on both sides. If Windows blocks incoming connections, an administrator can allow the default port on a private LAN:

```powershell
New-NetFirewallRule -DisplayName "secretPNG LAN" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 47831 -Profile Private -RemoteAddress LocalSubnet
```

## Security

Each file uses a fresh AES-256-GCM key wrapped with a password-derived key (PBKDF2-HMAC-SHA256, 600,000 rounds). Use a strong password and share it separately. An explicit `--password` can expose it in shell history and process listings. The public magic and dimensions are visible through pixel analysis. Resizing or changing pixel values can destroy the payload. LAN uses SHA-256 to check the transmitted PNG and has no peer authentication. Use a trusted network.

## Running tests

Activate the venv using the installer output, then run from the repository root on either platform:

```text
python -m unittest discover -s tests -q
```

## Publishing

Create a Git repository and stage the project files explicitly:

```powershell
git init -b main
git add -- .gitattributes .gitignore CHANGELOG.md LICENSE README.md install.ps1 install.sh pyproject.toml scripts src tests
git diff --cached --name-only
git diff --cached --check
git commit -m "Release secretPNG_share 1.0.0"
```

Keep local carrier images, recovered files, and release archives outside the commit. To publish with GitHub CLI, authenticate with `gh auth login` and run `gh repo create secretPNG_share --public --source . --remote origin --push`.

## License

MIT. See [LICENSE](LICENSE).
