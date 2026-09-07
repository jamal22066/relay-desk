"""Encrypt settings values at rest.

The key derives from SECRET_KEY, so a database dump alone does not yield
stored credentials. Rotating SECRET_KEY invalidates every stored secret —
they must be re-entered.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    digest = hashlib.sha256(("relay-settings:" + settings.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(plain: str) -> str:
    if not plain:
        return ""
    return _PREFIX + _fernet().encrypt(plain.encode()).decode()


def unseal(stored: str | None) -> str:
    if not stored:
        return ""
    if not stored.startswith(_PREFIX):
        return stored  # plaintext from a manual insert
    try:
        return _fernet().decrypt(stored[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        return ""  # SECRET_KEY changed; treat as unset
