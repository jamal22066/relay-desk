"""Materialise scheduled tickets.

Run by a systemd timer rather than a long-lived process: a schedule that fires
once a month does not justify a daemon, and a timer gives you the run history
in the journal for free.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import notify, services
from app.models import Event, Schedule, Ticket, User, utcnow
from app.sla import Calendar

log = logging.getLogger(__name__)


def advance(current: datetime, every: int, unit: str) -> datetime:
    """Next occurrence after `current`.

    Months are approximated as 30 days deliberately. Calendar-correct month
    arithmetic needs a policy for the 31st in February, and for a maintenance
    reminder "about a month later" is the honest intent.
    """
    if unit == "days":
        return current + timedelta(days=every)
    if unit == "weeks":
        return current + timedelta(weeks=every)
    if unit == "months":
        return current + timedelta(days=30 * every)
    raise ValueError(f"unknown recurrence unit: {unit}")


def _create_ticket(db: Session, sch: Schedule) -> Ticket:
    from sqlalchemy import func

    requester = db.scalar(
        select(User).where(
            func.lower(User.email) == sch.requester_email.lower(), User.is_active
        )
    )
    if requester is None:
        raise ValueError(f"no active account for {sch.requester_email}")

    now = utcnow()
    t = Ticket(
        ref=services.next_ref(db),
        subject=sch.subject,
        body=sch.body,
        track=sch.track,
        category=sch.category,
        priority=sch.priority,
        requester=requester.display_name,
        email=requester.email,
        org=requester.org,
        assignee=sch.assignee,
        created_at=now,
        updated_at=now,
    )
    t.due_at = Calendar(db).deadline(now, t.priority)
    db.add(t)
    db.flush()

    db.add(Event(
        ticket_id=t.id, at=now, actor=requester.display_name,
        kind="comment", body=sch.body, is_original=True,
    ))
    # the audit trail should show this was automatic, not filed by a person
    db.add(Event(
        ticket_id=t.id, at=now, actor="Scheduler", kind="system",
        body=f'Created automatically by schedule "{sch.name}" (#{sch.id})',
    ))
    db.flush()

    notify.on_new_ticket(db, t)
    return t


def run_due(db: Session, now: datetime | None = None) -> list[tuple[Schedule, str]]:
    """Fire every active schedule that is due. Returns (schedule, outcome)."""
    now = now or utcnow()
    results = []

    due = db.scalars(
        select(Schedule)
        .where(Schedule.status == "active", Schedule.next_run_at <= now)
        .order_by(Schedule.next_run_at)
        .with_for_update(skip_locked=True)
    ).all()

    for sch in due:
        try:
            t = _create_ticket(db, sch)
            sch.last_run_at = now
            sch.run_count += 1
            sch.last_error = None

            if sch.kind == "recurring" and sch.recur_every and sch.recur_unit:
                nxt = advance(sch.next_run_at, sch.recur_every, sch.recur_unit)
                # a schedule left unrun for a while should not fire repeatedly
                # to catch up: skip forward to the next future occurrence
                while nxt <= now:
                    nxt = advance(nxt, sch.recur_every, sch.recur_unit)
                if sch.recur_until and nxt > sch.recur_until:
                    sch.status = "completed"
                else:
                    sch.next_run_at = nxt
            else:
                sch.status = "completed"

            db.commit()
            results.append((sch, f"created {t.ref}"))
            log.info("schedule %s fired: %s", sch.id, t.ref)

        except Exception as e:
            db.rollback()
            sch = db.get(Schedule, sch.id)
            sch.last_error = f"{type(e).__name__}: {e}"[:2000]
            sch.status = "failed"
            try:
                notify.on_schedule_failed(db, sch, sch.last_error)
            except Exception:
                log.exception("could not queue the failure notification")
            db.commit()
            results.append((sch, f"failed: {e}"))
            log.error("schedule %s failed: %s", sch.id, e)

    return results
