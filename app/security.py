from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import settings

_ph = PasswordHasher()

ALGO = "HS256"
COOKIE = "relay_session"


def hash_password(raw: str) -> str:
    return _ph.hash(raw)


def verify_password(raw: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        return _ph.verify(stored, raw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    try:
        return _ph.check_needs_rehash(stored)
    except InvalidHashError:
        return False


def issue_token(user_id: int, email: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "email": email,
            "role": role,
            "iat": now,
            "exp": now + timedelta(hours=settings.session_hours),
        },
        settings.secret_key,
        algorithm=ALGO,
    )


def read_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGO])
    except jwt.PyJWTError:
        return None
