from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

PRIORITIES = ("P1", "P2", "P3", "P4")
STATUSES = ("New", "Open", "Waiting on customer", "Resolved", "Closed")
OPEN_STATUSES = ("New", "Open", "Waiting on customer")
TRACKS = ("saas", "it")
EVENT_KINDS = ("comment", "note", "system")

SLA_HOURS = {"P1": 4, "P2": 8, "P3": 24, "P4": 72}

ticket_seq = Sequence("ticket_ref_seq", start=1047, metadata=Base.metadata)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _in(col: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{col} IN ({joined})"


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(_in("priority", PRIORITIES), name="ck_ticket_priority"),
        CheckConstraint(_in("status", STATUSES), name="ck_ticket_status"),
        CheckConstraint(_in("track", TRACKS), name="ck_ticket_track"),
        Index("ix_tickets_status_priority", "status", "priority"),
        Index("ix_tickets_email", "email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref: Mapped[str] = mapped_column(String(16), unique=True, index=True)

    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)

    track: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(2), default="P3")
    status: Mapped[str] = mapped_column(String(32), default="New")

    requester: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200))
    org: Mapped[str] = mapped_column(String(120), default="Unspecified")
    assignee: Mapped[str] = mapped_column(String(120), default="Unassigned")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    first_response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_seconds: Mapped[int] = mapped_column(Integer, default=0)

    events: Mapped[list["Event"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="Event.at",
        lazy="selectin",
    )


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(_in("kind", EVENT_KINDS), name="ck_event_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text)
    # the customer's original description. Protected from deletion: a ticket
    # whose problem statement can vanish is worse than one you simply close.
    is_original: Mapped[bool] = mapped_column(Boolean, default=False)

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by: Mapped[str | None] = mapped_column(String(120), nullable=True)

    attachments: Mapped[list["Attachment"]] = relationship(
        primaryjoin="and_(Event.id == Attachment.event_id, "
                    "Attachment.deleted_at.is_(None))",
        lazy="selectin",
        viewonly=True,
    )

    ticket: Mapped["Ticket"] = relationship(back_populates="events")

AGENTS = ("Unassigned", "J. Nasir", "R. Okafor", "M. Delacroix", "S. Iyer")
AGENTS_DEFAULT_ME = "J. Nasir"

CATEGORIES = {
    "saas": [
        "Login & SSO",
        "Billing & licensing",
        "API / integration",
        "Service outage",
        "Data export",
        "Feature request",
    ],
    "it": [
        "Laptop & hardware",
        "Network / VPN",
        "Software install",
        "Account & password",
        "Email & calendar",
        "Security concern",
    ],
}


AUTH_SOURCES = ("local", "ldap", "oidc")
ROLES = ("admin", "agent", "customer")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(_in("role", ROLES), name="ck_user_role"),
        CheckConstraint(_in("auth_source", AUTH_SOURCES), name="ck_user_auth_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    org: Mapped[str] = mapped_column(String(120), default="Unspecified")

    auth_source: Mapped[str] = mapped_column(String(16), default="local")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ldap_dn: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # the IdP's stable subject identifier; email can change, sub does not
    oidc_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # kept only to pass as id_token_hint on RP-initiated logout
    oidc_id_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    # role resolution: role_override wins when set, else the LDAP group mapping,
    # else this stored value from the last successful login
    role: Mapped[str] = mapped_column(String(16), default="customer")
    role_override: Mapped[str | None] = mapped_column(String(16), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # local accounts must confirm their address before they can sign in or
    # receive notifications. LDAP accounts are verified by the directory.
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def effective_role(self) -> str:
        return self.role_override or self.role

    @property
    def is_staff(self) -> bool:
        """Admins can do everything agents can."""
        return self.effective_role in ("admin", "agent")


OUTBOX_STATUSES = ("queued", "sending", "sent", "failed", "suppressed")


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint(_in("status", OUTBOX_STATUSES), name="ck_outbox_status"),
        Index("ix_outbox_status_next", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    to_email: Mapped[str] = mapped_column(String(200))
    to_name: Mapped[str] = mapped_column(String(120), default="")
    subject: Mapped[str] = mapped_column(String(400))
    body: Mapped[str] = mapped_column(Text)

    ticket_ref: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(40))

    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)



class Setting(Base):
    """Key-value config, overriding .env at runtime. Secrets stored encrypted."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)


class Attachment(Base):
    """A file attached to an event.

    Hanging off the event rather than the ticket means an attachment on an
    internal note inherits that note's visibility for free.
    """
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), index=True
    )

    # the stored file is named by this, never by anything the client supplied
    stored_name: Mapped[str] = mapped_column(String(64), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)

    uploaded_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


SCHEDULE_KINDS = ("once", "recurring")
SCHEDULE_STATUSES = ("active", "paused", "completed", "failed")
RECUR_UNITS = ("days", "weeks", "months")


class Schedule(Base):
    """A ticket template that materialises on a date or a cadence.

    The lead-time case ("open a ticket 30 days before the maintenance window")
    is expressed by setting next_run_at to the computed date, rather than
    storing the target date and an offset separately.
    """
    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint(_in("kind", SCHEDULE_KINDS), name="ck_schedule_kind"),
        CheckConstraint(_in("status", SCHEDULE_STATUSES), name="ck_schedule_status"),
        CheckConstraint(_in("track", TRACKS), name="ck_schedule_track"),
        CheckConstraint(_in("priority", PRIORITIES), name="ck_schedule_priority"),
        Index("ix_schedules_due", "status", "next_run_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))

    kind: Mapped[str] = mapped_column(String(16), default="once")
    status: Mapped[str] = mapped_column(String(16), default="active")

    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recur_every: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recur_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    recur_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # the ticket this produces
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    track: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(2), default="P3")
    requester_email: Mapped[str] = mapped_column(String(200))
    assignee: Mapped[str] = mapped_column(String(120), default="Unassigned")

    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    # a schedule that silently stops firing is worse than one that visibly fails
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
