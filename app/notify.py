"""Decide who to email and queue it. Never sends inline."""
import logging

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.mailer import allowed
from app.models import Event, Outbox, Ticket, User, utcnow

log = logging.getLogger(__name__)


def _queue(db: Session, *, to_email: str, to_name: str, subject: str, body: str,
           reason: str, ticket_ref: str, event_id: int | None = None) -> None:
    if not settings.smtp_enabled or not to_email:
        return
    db.add(Outbox(
        to_email=to_email.lower().strip(), to_name=to_name or "",
        subject=subject, body=body, reason=reason,
        ticket_ref=ticket_ref, event_id=event_id,
        status="queued" if allowed(to_email) else "suppressed",
    ))


def _link(ref: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}/t/{ref}"


def _agent_email(db: Session, display_name: str) -> tuple[str, str] | None:
    u = db.scalar(select(User).where(User.display_name == display_name, User.is_active))
    return (u.email, u.display_name) if u else None


def on_event(db: Session, t: Ticket, ev: Event) -> None:
    """A comment or note was added."""
    if ev.kind != "comment":
        return  # notes and system events notify nobody

    from_customer = ev.actor == t.requester

    if from_customer:
        # tell the owning agent, unless nobody owns it
        if t.assignee and t.assignee != "Unassigned" and t.assignee != ev.actor:
            who = _agent_email(db, t.assignee)
            if who:
                _queue(db, to_email=who[0], to_name=who[1],
                       subject=f"[{t.ref}] {t.requester} replied: {t.subject}",
                       body=f"{ev.actor} replied to {t.ref}.\n\n{ev.body}\n\n{_link(t.ref)}",
                       reason="customer_reply", ticket_ref=t.ref, event_id=ev.id)
    else:
        _queue(db, to_email=t.email, to_name=t.requester,
               subject=f"[{t.ref}] {t.subject}",
               body=f"{ev.actor} replied to your ticket.\n\n{ev.body}\n\n{_link(t.ref)}",
               reason="agent_reply", ticket_ref=t.ref, event_id=ev.id)


def on_patch(db: Session, t: Ticket, changes: dict, actor: str) -> None:
    """Status, priority or assignee changed."""
    status = changes.get("status")
    if status in ("Resolved", "Closed") and actor != t.requester:
        _queue(db, to_email=t.email, to_name=t.requester,
               subject=f"[{t.ref}] {status}: {t.subject}",
               body=f"Your ticket has been marked {status.lower()} by {actor}.\n\n"
                    f"If this isn't sorted, reply and it reopens.\n\n{_link(t.ref)}",
               reason=f"ticket_{status.lower()}", ticket_ref=t.ref)

    assignee = changes.get("assignee")
    if assignee and assignee not in ("Unassigned", actor):
        who = _agent_email(db, assignee)
        if who:
            _queue(db, to_email=who[0], to_name=who[1],
                   subject=f"[{t.ref}] Assigned to you: {t.subject}",
                   body=f"{actor} assigned {t.ref} to you.\n\n"
                        f"{t.priority} · {t.category} · {t.requester} at {t.org}\n\n"
                        f"{t.body[:400]}\n\n{_link(t.ref)}",
                   reason="assigned", ticket_ref=t.ref)


def on_new_ticket(db: Session, t: Ticket) -> None:
    """A ticket was just filed."""
    from app import settings_store as store

    if store.get(db, "notify_new_ticket_customer"):
        _queue(
            db, to_email=t.email, to_name=t.requester,
            subject=f"[{t.ref}] We received your request: {t.subject}",
            body=(
                f"Thanks {t.requester}, your ticket is logged as {t.ref}.\n\n"
                f"{t.priority} · {t.category}\n\n"
                f"Someone will reply here. You can follow it at:\n{_link(t.ref)}"
            ),
            reason="ticket_receipt", ticket_ref=t.ref,
        )

    if not store.get(db, "notify_new_ticket_staff"):
        return

    # every active agent and admin, except whoever filed it
    staff = db.scalars(
        select(User).where(
            User.is_active,
            or_(
                User.role.in_(("agent", "admin")),
                User.role_override.in_(("agent", "admin")),
            ),
        )
    ).all()

    for u in staff:
        if u.email == t.email:
            continue
        _queue(
            db, to_email=u.email, to_name=u.display_name,
            subject=f"[{t.ref}] New {t.priority}: {t.subject}",
            body=(
                f"{t.requester} at {t.org} filed a new ticket.\n\n"
                f"{t.priority} · {t.category} · due {t.due_at:%Y-%m-%d %H:%M} UTC\n\n"
                f"{t.body[:600]}\n\n{_link(t.ref)}"
            ),
            reason="new_ticket", ticket_ref=t.ref,
        )
