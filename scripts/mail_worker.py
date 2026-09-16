"""Drain the outbox. Run continuously, or once with --once."""
import logging
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import mailer
from app.mailer import allowed, build, send  # noqa: E402
from app.models import Outbox, utcnow  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mail_worker")

MAX_ATTEMPTS = 5
BACKOFF_MINUTES = [1, 5, 20, 60]


def drain(limit: int = 20) -> int:
    db = SessionLocal()
    handled = 0
    try:
        rows = db.scalars(
            select(Outbox)
            .where(Outbox.status == "queued", Outbox.next_attempt_at <= utcnow())
            .order_by(Outbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()

        cfg = mailer.config(db)

        for row in rows:
            # Re-check: the allowlist may have tightened since queueing.
            # Verification links are exempt — the address was just typed by
            # whoever is registering, and the content is fixed with no ticket data.
            if row.reason != "verify_email" and not allowed(row.to_email, cfg.allowlist):
                row.status = "suppressed"
                row.last_error = "recipient not in allowlist"
                log.info("suppressed %s -> %s", row.id, row.to_email)
                handled += 1
                continue

            row.attempts += 1
            try:
                send(cfg, build(cfg, row.to_email, row.to_name, row.subject,
                                row.body, row.ticket_ref))
                row.status = "sent"
                row.sent_at = utcnow()
                row.last_error = None
                log.info("sent %s -> %s (%s)", row.id, row.to_email, row.reason)
            except Exception as e:
                row.last_error = f"{type(e).__name__}: {e}"[:2000]
                if row.attempts >= MAX_ATTEMPTS:
                    row.status = "failed"
                    log.error("giving up on %s after %s attempts: %s", row.id, row.attempts, e)
                else:
                    mins = BACKOFF_MINUTES[min(row.attempts - 1, len(BACKOFF_MINUTES) - 1)]
                    row.next_attempt_at = utcnow() + timedelta(minutes=mins)
                    log.warning("retry %s in %dm: %s", row.id, mins, e)
            handled += 1

        db.commit()
    finally:
        db.close()
    return handled


if __name__ == "__main__":
    once = "--once" in sys.argv
    _db = SessionLocal()
    try:
        _cfg = mailer.config(_db)
    finally:
        _db.close()
    if not _cfg.enabled:
        log.warning("email is disabled — nothing will send")
    log.info("allowlist: %s", _cfg.allowlist or "(empty — everything suppresses)")

    while True:
        n = drain()
        if once:
            log.info("processed %d", n)
            break
        time.sleep(10 if n else 30)
