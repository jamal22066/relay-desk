"""Create demo accounts. Idempotent. Local development only.

Passwords are never stored in this file. If SEED_PASSWORD is set, every new
account gets that password (convenient for the scripts/*_test.sh suite, which
reads the same variable). Otherwise each new account gets a random password,
printed once below — it is not recoverable afterwards.
"""
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402

PEOPLE = [
    ("arivera@example.com", "A. Rivera", "Relay", "agent"),
    ("rokafor@example.com", "R. Okafor", "Relay", "agent"),
    ("dana@example.com", "Dana Whitfield", "Acme", "customer"),
    ("priya@example.com", "Priya Raghavan", "Globex", "customer"),
]

shared = os.environ.get("SEED_PASSWORD")

db = SessionLocal()
for email, name, org, role in PEOPLE:
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        print("exists: ", email)
        continue
    pw = shared or secrets.token_urlsafe(12)
    db.add(User(
        email=email, display_name=name, org=org, role=role,
        auth_source="local", password_hash=hash_password(pw),
        email_verified=True,
    ))
    if shared:
        print("created:", email, f"({role})")
    else:
        print("created:", email, f"({role})", "password:", pw)
db.commit()
if not shared:
    print("(passwords shown once; set SEED_PASSWORD to choose your own)")
