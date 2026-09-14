from datetime import datetime, timezone

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.orm import Session

from app.models import AGENTS_DEFAULT_ME, Event, Ticket, utcnow

# due_at is stored, computed by app.sla.Calendar on every event that moves it
DUE_AT = Ticket.due_at

OPEN = ("New", "Open", "Waiting on customer")


def next_ref(db: Session) -> str:
    n = db.execute(text("SELECT nextval('ticket_ref_seq')")).scalar_one()
    return f"TKT-{n}"


def get_or_404(db: Session, ref: str) -> Ticket | None:
    return db.scalar(select(Ticket).where(Ticket.ref == ref))


def list_tickets(db: Session, view: str, track: str | None, q: str | None) -> list[Ticket]:
    stmt = select(Ticket)

    if view == "done":
        stmt = stmt.where(Ticket.status.not_in(OPEN))
    else:
        stmt = stmt.where(Ticket.status.in_(OPEN))

    if view == "mine":
        stmt = stmt.where(Ticket.assignee == AGENTS_DEFAULT_ME)
    elif view == "unassigned":
        stmt = stmt.where(Ticket.assignee == "Unassigned")
    elif view == "breach":
        stmt = stmt.where(Ticket.due_at.is_not(None), Ticket.due_at < func.now())

    if track:
        stmt = stmt.where(Ticket.track == track)

    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Ticket.ref).like(like),
                func.lower(Ticket.subject).like(like),
                func.lower(Ticket.requester).like(like),
                func.lower(Ticket.org).like(like),
                func.lower(Ticket.category).like(like),
            )
        )

    return list(db.scalars(stmt.order_by(Ticket.priority, Ticket.created_at)))


def add_event(db: Session, t: Ticket, actor: str, kind: str, body: str) -> Event:
    ev = Event(ticket_id=t.id, actor=actor, kind=kind, body=body, at=utcnow())
    db.add(ev)

    is_agent_reply = kind == "comment" and actor != t.requester
    if is_agent_reply:
        if t.first_response_at is None:
            t.first_response_at = ev.at
        if t.status == "New":
            t.status = "Open"
    elif kind == "comment" and t.status == "Waiting on customer":
        t.status = "Open"

    t.updated_at = ev.at
    return ev


def apply_patch(db: Session, t: Ticket, actor: str, **changes) -> list[Event]:
    from app.sla import Calendar

    cal = Calendar(db)
    old_status = t.status
    events = []
    for field, value in changes.items():
        if value is None or getattr(t, field) == value:
            continue
        setattr(t, field, value)
        label = {
            "status": f"Status changed to {value}",
            "priority": f"Priority changed to {value}",
            "assignee": f"Assigned to {value}",
        }[field]
        events.append(Event(ticket_id=t.id, actor=actor, kind="system", body=label))
        if field == "status":
            t.resolved_at = utcnow() if value in ("Resolved", "Closed") else None
        if field == "priority":
            # deadline recalculates from the original creation time
            t.due_at = cal.deadline(t.created_at, t.priority, t.paused_seconds or 0)
    if cal.pause_enabled and t.status != old_status:
        if t.status == "Waiting on customer":
            t.paused_at = utcnow()
        elif old_status == "Waiting on customer" and t.paused_at:
            # the clock stood still: push the deadline out by the working time lost
            lost = cal.elapsed(t.paused_at, utcnow())
            t.paused_seconds = (t.paused_seconds or 0) + lost * 60
            t.due_at = cal.add(t.due_at or t.created_at, lost)
            t.paused_at = None

    for e in events:
        db.add(e)
    if events:
        t.updated_at = utcnow()
    return events


def counts(db: Session) -> dict[str, int]:
    return {v: len(list_tickets(db, v, None, None)) for v in
            ("all", "mine", "unassigned", "breach", "done")}


def track_counts(db: Session) -> dict[str, int]:
    return {
        t: db.scalar(
            select(func.count()).select_from(Ticket)
            .where(Ticket.track == t, Ticket.status.in_(OPEN))
        )
        for t in ("saas", "it")
    }


def delete_event(
    db: Session, t: Ticket, event_id: int, actor: str, as_requester: bool = False
) -> tuple[Event | None, str | None]:
    ev = db.get(Event, event_id)
    if ev is None or ev.ticket_id != t.id:
        return None, "No such message on this ticket"
    if ev.kind == "system":
        return None, "System events are part of the audit trail and cannot be removed"
    if ev.is_original:
        return None, "The original description cannot be removed. Close the ticket instead."
    if ev.deleted_at is not None:
        return ev, None
    if as_requester and (ev.kind != "comment" or ev.actor != t.requester):
        return None, "You can only remove your own messages"

    ev.deleted_at = utcnow()
    ev.deleted_by = actor
    t.updated_at = ev.deleted_at
    return ev, None
