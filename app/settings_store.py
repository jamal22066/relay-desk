"""Runtime settings: database first, .env as fallback.

Every key declares a type and whether it holds a secret. Secrets are sealed at
rest and never returned to a client — the API sends a mask, and an empty submit
leaves the stored value alone.
"""
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings as env
from app.models import Setting, utcnow
from app.secrets_box import seal, unseal

Kind = Literal["str", "int", "bool", "json"]

MASK = "••••••••"


@dataclass(frozen=True)
class Spec:
    key: str
    kind: Kind
    section: str
    label: str
    env_attr: str | None = None
    secret: bool = False
    help: str = ""


SPECS: list[Spec] = [
    # --- LDAP ---
    Spec("ldap_enabled", "bool", "ldap", "Enable LDAP", "ldap_enabled"),
    Spec("ldap_server", "str", "ldap", "Server URL", "ldap_server",
         help="ldaps://host:636 in production — simple binds send passwords in the clear over ldap://"),
    Spec("ldap_bind_dn", "str", "ldap", "Service account DN", "ldap_bind_dn"),
    Spec("ldap_bind_password", "str", "ldap", "Service account password", "ldap_bind_password", secret=True),
    Spec("ldap_user_base", "str", "ldap", "User search base", "ldap_user_base"),
    Spec("ldap_user_filter", "str", "ldap", "User filter", "ldap_user_filter",
         help="{email} is substituted and escaped"),
    Spec("ldap_group_base", "str", "ldap", "Group search base", "ldap_group_base"),
    Spec("ldap_agent_group", "str", "ldap", "Agent group DN", "ldap_agent_group",
         help="Members of this group get the agent role"),
    Spec("ldap_attr_name", "str", "ldap", "Display name attribute", "ldap_attr_name"),
    Spec("ldap_attr_email", "str", "ldap", "Email attribute", "ldap_attr_email"),
    Spec("ldap_tls_verify", "bool", "ldap", "Verify TLS certificate", "ldap_tls_verify"),

    # --- SMTP ---
    Spec("smtp_enabled", "bool", "smtp", "Enable email", "smtp_enabled"),
    Spec("smtp_host", "str", "smtp", "SMTP host", "smtp_host"),
    Spec("smtp_port", "int", "smtp", "Port", "smtp_port"),
    Spec("smtp_username", "str", "smtp", "Username", "smtp_username"),
    Spec("smtp_password", "str", "smtp", "Password", "smtp_password", secret=True),
    Spec("smtp_from", "str", "smtp", "From address", "smtp_from",
         help="Must match the authenticated account or the relay will reject it"),
    Spec("smtp_from_name", "str", "smtp", "From name", "smtp_from_name"),
    Spec("smtp_allowlist", "str", "smtp", "Recipient allowlist", "smtp_allowlist",
         help="Comma separated addresses or @domains. '*' allows everyone — only set that when routing is trusted."),
    Spec("app_base_url", "str", "smtp", "App URL for email links", "app_base_url"),

    # --- notifications ---
    Spec("notify_agent_reply", "bool", "notifications", "Email customer on agent reply"),
    Spec("notify_ticket_resolved", "bool", "notifications", "Email customer on resolve or close"),
    Spec("notify_assigned", "bool", "notifications", "Email agent when assigned a ticket"),
    Spec("notify_customer_reply", "bool", "notifications", "Email owning agent on customer reply"),
    Spec("notify_new_ticket_staff", "bool", "notifications", "Email all staff when a ticket is filed"),
    Spec("notify_new_ticket_customer", "bool", "notifications", "Send the customer a receipt when they file"),
    Spec("notify_signup", "bool", "notifications", "Email admins when someone registers"),
    Spec("notify_verified", "bool", "notifications", "Email admins when someone confirms their address"),

    # --- SLA ---
    Spec("sla_p1_hours", "int", "sla", "P1 target (hours)"),
    Spec("sla_p2_hours", "int", "sla", "P2 target (hours)"),
    Spec("sla_p3_hours", "int", "sla", "P3 target (hours)"),
    Spec("sla_p4_hours", "int", "sla", "P4 target (hours)"),
    Spec("sla_business_hours_only", "bool", "sla", "Count business hours only"),
    Spec("sla_pause_on_customer", "bool", "sla", "Pause while waiting on customer"),
    Spec("business_day_start", "str", "sla", "Working day starts", help="24h clock, e.g. 09:00"),
    Spec("business_day_end", "str", "sla", "Working day ends", help="e.g. 17:00"),
    Spec("business_days", "json", "sla", "Working days", help="0=Monday … 6=Sunday"),
    Spec("business_timezone", "str", "sla", "Timezone", help="e.g. America/New_York"),
    Spec("business_holidays", "json", "sla", "Holidays", help="List of YYYY-MM-DD dates"),

    # --- desk ---
    Spec("categories", "json", "desk", "Ticket categories"),
    Spec("agents", "json", "desk", "Agent roster"),

    # --- security ---
    Spec("session_hours", "int", "security", "Session length (hours)", "session_hours"),
    Spec("cookie_secure", "bool", "security", "Require HTTPS for the session cookie", "cookie_secure"),
]

BY_KEY = {s.key: s for s in SPECS}

DEFAULTS: dict[str, Any] = {
    "notify_agent_reply": True,
    "notify_ticket_resolved": True,
    "notify_assigned": True,
    "notify_customer_reply": True,
    "notify_new_ticket_staff": True,
    "notify_new_ticket_customer": True,
    "notify_signup": True,
    "notify_verified": True,
    "sla_p1_hours": 4,
    "sla_p2_hours": 8,
    "sla_p3_hours": 24,
    "sla_p4_hours": 72,
    "sla_business_hours_only": False,
    "sla_pause_on_customer": False,
    "business_day_start": "09:00",
    "business_day_end": "17:00",
    "business_days": [0, 1, 2, 3, 4],
    "business_timezone": "America/New_York",
    "business_holidays": [],
}


def _decode(spec: Spec, raw: str) -> Any:
    if spec.kind == "bool":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if spec.kind == "int":
        return int(raw)
    if spec.kind == "json":
        import json
        return json.loads(raw)
    return raw


def _encode(spec: Spec, value: Any) -> str:
    if spec.kind == "json":
        import json
        return json.dumps(value)
    if spec.kind == "bool":
        return "true" if value else "false"
    return str(value)


def get(db: Session, key: str) -> Any:
    """Database value, else .env, else the declared default."""
    spec = BY_KEY.get(key)
    if spec is None:
        raise KeyError(key)

    row = db.get(Setting, key)
    if row is not None and row.value not in (None, ""):
        raw = unseal(row.value) if spec.secret else row.value
        if raw != "":
            return _decode(spec, raw)

    if spec.env_attr:
        return getattr(env, spec.env_attr)
    return DEFAULTS.get(key)


def all_values(db: Session) -> dict[str, Any]:
    return {s.key: get(db, s.key) for s in SPECS}


def put(db: Session, key: str, value: Any, actor: str) -> None:
    spec = BY_KEY.get(key)
    if spec is None:
        raise KeyError(key)
    if spec.secret and value in ("", None, MASK):
        return  # empty submit leaves the stored secret alone

    encoded = _encode(spec, value)
    stored = seal(encoded) if spec.secret else encoded

    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, is_secret=spec.secret)
        db.add(row)
    row.value = stored
    row.updated_at = utcnow()
    row.updated_by = actor


def clear(db: Session, key: str) -> None:
    """Drop the override so the .env value applies again."""
    row = db.get(Setting, key)
    if row is not None:
        db.delete(row)
