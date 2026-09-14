from datetime import datetime, timedelta
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.models import OPEN_STATUSES, SLA_HOURS

Priority = Literal["P1", "P2", "P3", "P4"]
Status = Literal["New", "Open", "Waiting on customer", "Resolved", "Closed"]
Track = Literal["saas", "it"]


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_name: str
    content_type: str
    size_bytes: int
    uploaded_by: str


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    attachments: list[AttachmentOut] = []
    at: datetime
    actor: str
    kind: str
    body: str
    is_original: bool = False
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    @model_validator(mode="after")
    def redact_deleted(self):
        if self.deleted_at is not None:
            self.body = ""
        return self


class TicketBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ref: str
    subject: str
    body: str
    track: Track
    category: str
    priority: Priority
    status: Status
    requester: str
    email: str
    org: str
    assignee: str
    created_at: datetime
    updated_at: datetime
    first_response_at: datetime | None
    resolved_at: datetime | None

    due_at: datetime | None = None

    @computed_field
    @property
    def breaching(self) -> bool:
        if self.status not in OPEN_STATUSES or self.due_at is None:
            return False
        return datetime.now(self.created_at.tzinfo) > self.due_at


class TicketSummary(TicketBase):
    pass


class TicketDetail(TicketBase):
    events: list[EventOut] = []


class TicketCreate(BaseModel):
    subject: str = Field(min_length=3, max_length=300)
    body: str = Field(min_length=3)
    track: Track
    category: str = Field(max_length=64)
    priority: Priority = "P3"
    # agents only: file on behalf of an existing account. Ignored for customers.
    requester_email: str | None = None



class TicketPatch(BaseModel):
    status: Status | None = None
    priority: Priority | None = None
    assignee: str | None = Field(default=None, max_length=120)


class EventCreate(BaseModel):
    body: str = Field(min_length=1)
    kind: Literal["comment", "note"] = "comment"
    actor: str | None = None
