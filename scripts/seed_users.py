"""Create demo accounts. Idempotent. Local development passwords only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402

PEOPLE = [
    ("jamal@relaydesk.io", "J. Nasir", "Relay", "agent", "devpassword123"),
    ("rokafor@relaydesk.io", "R. Okafor", "Relay", "agent", "devpassword123"),
    ("dana@northgate.io", "Dana Whitfield", "Northgate", "customer", "devpassword123"),
    ("priya@ferrous.dev", "Priya Raghavan", "Ferrous", "customer", "devpassword123"),
]

db = SessionLocal()
for email, name, org, role, pw in PEOPLE:
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        print("exists: ", email)
        continue
    db.add(User(
        email=email, display_name=name, org=org, role=role,
        auth_source="local", password_hash=hash_password(pw),
    ))
    print("created:", email, f"({role})")
db.commit()
