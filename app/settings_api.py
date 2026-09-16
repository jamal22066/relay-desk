import smtplib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import mailer
from app import settings_store as store
from app.auth import current_user, require_admin
from app.db import get_db
from app.models import Setting, User

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])

SECTIONS = [
    ("ldap", "Directory", "How staff authenticate against LDAP or FreeIPA."),
    ("smtp", "Email delivery", "Outbound relay and the recipient safety guard."),
    ("notifications", "Notifications", "Which events generate email."),
    ("sla", "Service levels", "Response targets and working hours."),
    ("desk", "Desk", "Categories and the agent roster."),
    ("security", "Security", "Session and cookie behaviour."),
]


class SettingsIn(BaseModel):
    values: dict[str, Any]


@router.get("/settings")
def read_settings(db: Session = Depends(get_db)):
    values = store.all_values(db)
    out = []
    for key, title, blurb in SECTIONS:
        fields = []
        for spec in (s for s in store.SPECS if s.section == key):
            v = values.get(spec.key)
            fields.append({
                "key": spec.key,
                "label": spec.label,
                "kind": spec.kind,
                "help": spec.help,
                "secret": spec.secret,
                "value": (store.MASK if v else "") if spec.secret else v,
                "overridden": db.get(Setting, spec.key) is not None,
            })
        out.append({"key": key, "title": title, "blurb": blurb, "fields": fields})
    return {"sections": out}


@router.put("/settings")
def write_settings(payload: SettingsIn, me: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    unknown = [k for k in payload.values if k not in store.BY_KEY]
    if unknown:
        raise HTTPException(422, f"Unknown settings: {', '.join(unknown)}")

    for key, value in payload.values.items():
        store.put(db, key, value, me.display_name)
    db.commit()
    return read_settings(db)


@router.post("/settings/reset/{key}")
def reset_setting(key: str, db: Session = Depends(get_db)):
    if key not in store.BY_KEY:
        raise HTTPException(404, f"Unknown setting {key}")
    store.clear(db, key)
    db.commit()
    return {"key": key, "value": store.get(db, key)}


class LdapTest(BaseModel):
    email: str
    password: str


@router.post("/test/ldap")
def test_ldap(payload: LdapTest):
    """Validate directory settings against a real credential before saving."""
    from app.ldap_client import authenticate
    ident = authenticate(payload.email, payload.password)
    if ident is None:
        return {"ok": False, "detail": "Bind failed. Check the server, base DN, filter and credentials."}
    return {
        "ok": True,
        "detail": f"Bound as {ident.display_name}",
        "dn": ident.dn,
        "role": "agent" if ident.is_agent else "customer",
    }


class SmtpTest(BaseModel):
    to: str


@router.post("/test/smtp")
def test_smtp(payload: SmtpTest):
    from app.mailer import allowed, build, send

    # The allowlist guards automated notification routing, where a bug could mail
    # many people. This is a deliberate one-off with fixed content, so it sends
    # regardless — but says so when the recipient is outside the list.
    cfg = mailer.config(db)
    outside = not allowed(payload.to, cfg.allowlist)
    try:
        send(cfg, build(cfg, payload.to, "", "Relay desk settings test",
                   "Sent from the admin settings page. Delivery is working."))
        note = " (outside the allowlist — notifications to this address would be suppressed)" if outside else ""
        return {"ok": True, "detail": f"Sent to {payload.to}{note}"}
    except smtplib.SMTPAuthenticationError:
        return {"ok": False, "detail": "The relay rejected the username or password."}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


@router.post("/sla/recompute")
def recompute_sla(db: Session = Depends(get_db)):
    """Reapply current SLA settings to every open ticket."""
    from sqlalchemy import select

    from app.models import OPEN_STATUSES, Ticket
    from app.sla import Calendar

    cal = Calendar(db)
    n = 0
    for t in db.scalars(select(Ticket).where(Ticket.status.in_(OPEN_STATUSES))):
        t.due_at = cal.deadline(t.created_at, t.priority, t.paused_seconds or 0)
        n += 1
    db.commit()
    return {
        "ok": True,
        "detail": f"Recomputed {n} open ticket(s)"
                  f" — business hours {'on' if cal.business_only else 'off'}.",
    }


# ---------------------------------------------------------------- users


def _active_admin_count(db: Session) -> int:
    from sqlalchemy import or_, select

    from app.models import User as U

    return len(db.scalars(
        select(U).where(
            U.is_active,
            or_(U.role == "admin", U.role_override == "admin"),
        )
    ).all())


def _guard_last_admin(db: Session, target: User, me: User, action: str) -> None:
    """Refuse changes that would remove the last way in."""
    if target.id == me.id:
        raise HTTPException(400, f"You cannot {action} your own account.")
    if target.effective_role == "admin" and _active_admin_count(db) <= 1:
        raise HTTPException(400, f"Cannot {action} the last active administrator.")


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    from sqlalchemy import func, select

    from app.models import Ticket, User as U

    counts = dict(
        db.execute(
            select(Ticket.email, func.count()).group_by(Ticket.email)
        ).all()
    )

    rows = db.scalars(select(U).order_by(U.role, U.email)).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "org": u.org,
            "role": u.effective_role,
            "stored_role": u.role,
            "role_override": u.role_override,
            "auth_source": u.auth_source,
            "is_active": u.is_active,
            "email_verified": u.email_verified,
            "created_at": u.created_at,
            "last_login_at": u.last_login_at,
            "ticket_count": counts.get(u.email, 0),
        }
        for u in rows
    ]


class UserPatch(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    email_verified: bool | None = None


@router.patch("/users/{user_id}")
def patch_user(user_id: int, payload: UserPatch,
               me: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.models import ROLES, User as U, utcnow

    target = db.get(U, user_id)
    if target is None:
        raise HTTPException(404, "No such account")

    if payload.role is not None:
        if payload.role not in ROLES:
            raise HTTPException(422, f"Role must be one of {', '.join(ROLES)}")
        if payload.role != "admin":
            _guard_last_admin(db, target, me, "demote")
        # role_override wins over whatever LDAP says, so set that
        target.role_override = payload.role

    if payload.is_active is not None:
        if not payload.is_active:
            _guard_last_admin(db, target, me, "deactivate")
        target.is_active = payload.is_active

    if payload.email_verified is not None:
        target.email_verified = payload.email_verified
        target.verified_at = utcnow() if payload.email_verified else None

    db.commit()
    return {"ok": True, "detail": f"Updated {target.email}"}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, me: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    from app.models import User as U

    target = db.get(U, user_id)
    if target is None:
        raise HTTPException(404, "No such account")
    _guard_last_admin(db, target, me, "delete")

    email = target.email
    db.delete(target)
    db.commit()
    # tickets keep the requester name and address: the history stays intact
    return {"ok": True, "detail": f"Deleted {email}. Their tickets remain."}


@router.post("/users/{user_id}/resend-verification")
def resend_verification(user_id: int, db: Session = Depends(get_db)):
    from app.auth_api import _send_verification
    from app.models import User as U

    target = db.get(U, user_id)
    if target is None:
        raise HTTPException(404, "No such account")
    if target.email_verified:
        return {"ok": False, "detail": "That address is already verified."}
    if target.auth_source != "local":
        return {"ok": False, "detail": "Directory accounts do not use email verification."}

    _send_verification(db, target)
    return {"ok": True, "detail": f"Verification link queued for {target.email}"}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    from datetime import timedelta

    from sqlalchemy import func, select

    from app.models import Event, OPEN_STATUSES, Outbox, Schedule, Ticket, User as U, utcnow

    def counts(col):
        return dict(db.execute(select(col, func.count()).group_by(col)).all())

    now = utcnow()
    breaching = db.scalar(
        select(func.count()).select_from(Ticket).where(
            Ticket.status.in_(OPEN_STATUSES),
            Ticket.due_at.is_not(None),
            Ticket.due_at < now,
        )
    )
    due_soon = db.scalar(
        select(func.count()).select_from(Ticket).where(
            Ticket.status.in_(OPEN_STATUSES),
            Ticket.due_at.between(now, now + timedelta(hours=4)),
        )
    )

    recent = db.scalars(
        select(Event).order_by(Event.at.desc()).limit(12)
    ).all()
    refs = dict(db.execute(select(Ticket.id, Ticket.ref)).all())

    return {
        "tickets": {
            "by_status": counts(Ticket.status),
            "by_priority": counts(Ticket.priority),
            "unassigned": db.scalar(
                select(func.count()).select_from(Ticket).where(
                    Ticket.assignee == "Unassigned",
                    Ticket.status.in_(OPEN_STATUSES),
                )
            ),
            "breaching": breaching,
            "due_soon": due_soon,
        },
        "outbox": counts(Outbox.status),
        "schedules": {
            "active": db.scalar(
                select(func.count()).select_from(Schedule).where(Schedule.status == "active")
            ),
            "failed": db.scalar(
                select(func.count()).select_from(Schedule).where(Schedule.status == "failed")
            ),
        },
        "users": {
            "total": db.scalar(select(func.count()).select_from(U)),
            "unverified": db.scalar(
                select(func.count()).select_from(U).where(
                    U.email_verified.is_(False), U.auth_source == "local"
                )
            ),
            "inactive": db.scalar(
                select(func.count()).select_from(U).where(U.is_active.is_(False))
            ),
        },
        "recent": [
            {
                "at": e.at,
                "actor": e.actor,
                "kind": e.kind,
                "ticket_ref": refs.get(e.ticket_id),
                "summary": (e.body[:90] if not e.deleted_at else "(removed)"),
            }
            for e in recent
        ],
    }


@router.get("/outbox")
def list_outbox(status: str | None = None, limit: int = 100,
                db: Session = Depends(get_db)):
    from sqlalchemy import select

    from app.models import Outbox

    cfg = mailer.config(db)
    stmt = select(Outbox).order_by(Outbox.id.desc()).limit(min(limit, 500))
    if status:
        stmt = stmt.where(Outbox.status == status)

    rows = db.scalars(stmt).all()
    return {
        "from_address": cfg.from_addr or "(not configured)",
        "smtp_enabled": cfg.enabled,
        "allowlist": cfg.allowlist or ["(empty — everything suppresses)"],
        "messages": [
            {
                "id": r.id,
                "status": r.status,
                "reason": r.reason,
                "to_email": r.to_email,
                "to_name": r.to_name,
                "subject": r.subject,
                "body": r.body,
                "ticket_ref": r.ticket_ref,
                "attempts": r.attempts,
                "last_error": r.last_error,
                "created_at": r.created_at,
                "next_attempt_at": r.next_attempt_at,
                "sent_at": r.sent_at,
            }
            for r in rows
        ],
    }


@router.post("/outbox/{msg_id}/retry")
def retry_message(msg_id: int, db: Session = Depends(get_db)):
    from app.models import Outbox, utcnow

    row = db.get(Outbox, msg_id)
    if row is None:
        raise HTTPException(404, "No such message")
    if row.status == "sent":
        return {"ok": False, "detail": "That message was already delivered."}

    row.status = "queued"
    row.attempts = 0
    row.last_error = None
    row.next_attempt_at = utcnow()
    db.commit()
    return {"ok": True, "detail": f"Requeued message {msg_id}. The worker picks it up shortly."}
