"""Email verification tokens.

Signed with SECRET_KEY and scoped to the user id plus their current email, so a
token stops working if the address changes. No storage: the signature is the
proof, and expiry is carried in the token.
"""
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

PURPOSE = "verify-email"
TTL_HOURS = 48


def issue(user_id: int, email: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "email": email.lower().strip(),
            "purpose": PURPOSE,
            "iat": now,
            "exp": now + timedelta(hours=TTL_HOURS),
        },
        settings.secret_key,
        algorithm="HS256",
    )


def read(token: str) -> dict | None:
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if claims.get("purpose") != PURPOSE:
        return None
    return claims
