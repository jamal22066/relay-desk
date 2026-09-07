"""Recompute due_at for open tickets against current settings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import OPEN_STATUSES, Ticket  # noqa: E402
from app.sla import Calendar  # noqa: E402

only_open = "--all" not in sys.argv
db = SessionLocal()
cal = Calendar(db)

stmt = select(Ticket)
if only_open:
    stmt = stmt.where(Ticket.status.in_(OPEN_STATUSES))

n = 0
for t in db.scalars(stmt):
    t.due_at = cal.deadline(t.created_at, t.priority, t.paused_seconds or 0)
    n += 1
db.commit()
print(f"recomputed {n} ticket(s) — business_hours={cal.business_only}, targets={cal.targets}")
