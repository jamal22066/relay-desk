"""SMTP delivery for queued outbox rows.

The allowlist is a development guard: any recipient not matching an entry is
marked suppressed rather than sent. Set SMTP_ALLOWLIST="*" only once you trust
the notification logic — this database contains real-looking external addresses.
"""
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.config import settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmtpConfig:
    """Effective mail settings: database value, else .env, else default.

    Resolved per call rather than read from `app.config.settings`, because the
    environment object is loaded once at import and never sees an administrator
    editing these on the settings page. Reading it directly meant a changed
    allowlist or From address was displayed as saved while delivery carried on
    using the old value.
    """
    enabled: bool
    host: str
    port: int
    username: str
    password: str
    from_addr: str
    from_name: str
    allowlist: list[str]
    base_url: str

    @property
    def domain(self) -> str:
        return self.from_addr.split("@")[-1]


def config(db) -> SmtpConfig:
    from app import settings_store as store

    raw = store.get(db, "smtp_allowlist") or ""
    return SmtpConfig(
        enabled=bool(store.get(db, "smtp_enabled")),
        host=store.get(db, "smtp_host") or "",
        port=int(store.get(db, "smtp_port") or 0),
        username=store.get(db, "smtp_username") or "",
        password=store.get(db, "smtp_password") or "",
        from_addr=store.get(db, "smtp_from") or "",
        from_name=store.get(db, "smtp_from_name") or "",
        allowlist=[a.strip().lower() for a in raw.split(",") if a.strip()],
        base_url=store.get(db, "app_base_url") or "",
    )


def allowed(recipient: str, rules: list[str]) -> bool:
    if not rules:
        return False
    if "*" in rules:
        return True
    r = recipient.lower().strip()
    for rule in rules:
        if rule.startswith("@") and r.endswith(rule):
            return True
        if r == rule:
            return True
    return False


def build(cfg: SmtpConfig, to_email: str, to_name: str, subject: str, body: str,
          ticket_ref: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.from_name, cfg.from_addr))
    msg["To"] = formataddr((to_name, to_email)) if to_name else to_email
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=cfg.domain)
    if ticket_ref:
        # threads replies together in the recipient's client
        anchor = f"<ticket-{ticket_ref.lower()}@{cfg.domain}>"
        msg["References"] = anchor
        msg["In-Reply-To"] = anchor
    msg.set_content(body)
    return msg


def send(cfg: SmtpConfig, msg: EmailMessage) -> None:
    """Raises on failure — the caller records the error and schedules a retry."""
    with smtplib.SMTP(cfg.host, cfg.port, timeout=settings.smtp_timeout) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        if cfg.username:
            s.login(cfg.username, cfg.password)
        s.send_message(msg)
