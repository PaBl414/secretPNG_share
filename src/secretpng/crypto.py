"""AES-GCM encryption under independent per-file keys."""

from hashlib import pbkdf2_hmac

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import AppError, BAD_PASSWORD, INTEGRITY
from .metadata import PREFIX

WRAP_DOMAIN = b"SPNG1-W\x00"
META_DOMAIN = b"SPNG1-M\x00"
DATA_DOMAIN = b"SPNG1-D\x00"


def _kek(password: bytes, salt: bytes) -> AESGCM:
    return AESGCM(pbkdf2_hmac("sha256", password, salt, 600000, dklen=32))


def _data_nonce(nonce: bytes) -> bytes:
    return nonce[:-1] + bytes([nonce[-1] ^ 1])


def seal(password: bytes, prefix: bytes, private: bytes, data: bytes) -> tuple[bytes, bytes, bytes]:
    """Wrap a new key, then authenticate metadata and data separately."""
    salt, wrap_nonce, nonce = PREFIX.unpack(prefix)[-3:]
    key = AESGCM.generate_key(bit_length=256)
    wrapped = _kek(password, salt).encrypt(wrap_nonce, key, WRAP_DOMAIN + prefix)
    public = prefix + wrapped
    cipher = AESGCM(key)
    private_ct = cipher.encrypt(nonce, private, META_DOMAIN + public)
    data_ct = cipher.encrypt(_data_nonce(nonce), data, DATA_DOMAIN + public + private_ct)
    return wrapped, private_ct, data_ct


def unseal(password: bytes, public: bytes, private_ct: bytes, data_ct: bytes) -> tuple[bytes, bytes]:
    """Authenticate every encrypted field before releasing plaintext."""
    prefix = public[:PREFIX.size]
    salt, wrap_nonce, nonce = PREFIX.unpack(prefix)[-3:]
    try:
        key = _kek(password, salt).decrypt(wrap_nonce, public[PREFIX.size:], WRAP_DOMAIN + prefix)
    except InvalidTag as error:
        raise AppError(6, BAD_PASSWORD) from error
    cipher = AESGCM(key)
    try:
        private = cipher.decrypt(nonce, private_ct, META_DOMAIN + public)
        data = cipher.decrypt(_data_nonce(nonce), data_ct, DATA_DOMAIN + public + private_ct)
    except InvalidTag as error:
        raise AppError(6, INTEGRITY) from error
    return private, data
