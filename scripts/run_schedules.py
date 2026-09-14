"""Fire any due schedules. Intended for a systemd timer."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.scheduler import run_due  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

db = SessionLocal()
try:
    results = run_due(db)
    if not results:
        print("nothing due")
    for sch, outcome in results:
        print(f"  [{sch.id}] {sch.name}: {outcome}")
finally:
    db.close()
