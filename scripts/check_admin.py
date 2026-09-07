"""Warn if no local admin exists. A directory outage would lock everyone out."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import or_, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402

db = SessionLocal()
admins = db.scalars(
    select(User).where(
        or_(User.role == "admin", User.role_override == "admin"), User.is_active
    )
).all()

local = [u for u in admins if u.auth_source == "local"]
for u in admins:
    print(f"  {u.email:32} {u.auth_source:6} {'(local password)' if u.auth_source == 'local' else ''}")

if not admins:
    sys.exit("\nNo admin exists. Promote one with SQL before deploying.")
if not local:
    sys.exit("\nEvery admin is LDAP-only. A directory outage locks you out entirely.")
print(f"\n{len(local)} local admin(s) — recoverable if LDAP breaks.")
