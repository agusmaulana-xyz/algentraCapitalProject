"""Authenticated encryption for MT5 account tokens that ALGENTRA can show to their owner."""

from base64 import urlsafe_b64encode
import hashlib
import hmac

from .config import get_settings


class TokenEncryptionError(Exception):
    pass


def _fernet(purpose: bytes = b"algentra:mt5-account-token:v1"):
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover - dependency is installed from requirements.txt
        raise TokenEncryptionError("Dependensi enkripsi token belum terpasang") from exc

    secret = get_settings().app_secret_key.get_secret_value().encode("utf-8")
    # Derive a purpose-specific encryption key without reusing APP_SECRET_KEY directly.
    material = hmac.new(secret, purpose, hashlib.sha256).digest()
    return Fernet(urlsafe_b64encode(material))


def encrypt_account_token(token: str) -> str:
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_account_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except Exception as exc:
        # Do not expose ciphertext or cryptography details in an API error.
        raise TokenEncryptionError("Token akun tidak dapat dipulihkan") from exc


def encrypt_managed_copy_password(password: str) -> str:
    return _fernet(b"algentra:managed-copy-password:v1").encrypt(password.encode("utf-8")).decode("ascii")


def decrypt_managed_copy_password(ciphertext: str) -> str:
    try:
        return _fernet(b"algentra:managed-copy-password:v1").decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise TokenEncryptionError("Kredensial akun tidak dapat dipulihkan") from exc
