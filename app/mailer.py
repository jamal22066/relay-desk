"""SMTP delivery for queued outbox rows.

The allowlist is a development guard: any recipient not matching an entry is
marked suppressed rather than sent. Set SMTP_ALLOWLIST="*" only once you trust
the notification logic — this database contains real-looking external addresses.
"""
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.config import settings

log = logging.getLogger(__name__)


def allowed(recipient: str) -> bool:
    rules = settings.allowlist
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


def build(to_email: str, to_name: str, subject: str, body: str,
          ticket_ref: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.smtp_from_name, settings.smtp_from))
    msg["To"] = formataddr((to_name, to_email)) if to_name else to_email
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=settings.smtp_from.split("@")[-1])
    if ticket_ref:
        # threads replies together in the recipient's client
        anchor = f"<ticket-{ticket_ref.lower()}@{settings.smtp_from.split('@')[-1]}>"
        msg["References"] = anchor
        msg["In-Reply-To"] = anchor
    msg.set_content(body)
    return msg


def send(msg: EmailMessage) -> None:
    """Raises on failure — the caller records the error and schedules a retry."""
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port,
                      timeout=settings.smtp_timeout) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        if settings.smtp_username:
            s.login(settings.smtp_username, settings.smtp_password)
        s.send_message(msg)
