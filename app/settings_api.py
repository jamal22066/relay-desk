import smtplib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import settings_store as store
from app.auth import require_admin
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
    if not allowed(payload.to):
        return {"ok": False, "detail": f"{payload.to} is not in the allowlist — refusing to send."}
    try:
        send(build(payload.to, "", "Relay desk settings test",
                   "Sent from the admin settings page. Delivery is working."))
        return {"ok": True, "detail": f"Sent to {payload.to}"}
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
