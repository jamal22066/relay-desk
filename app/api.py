from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services
from app.db import get_db
from app.models import (
    AGENTS,
    AGENTS_DEFAULT_ME,
    CATEGORIES,
    PRIORITIES,
    SLA_HOURS,
    STATUSES,
    Ticket,
)
from app.schemas import (
    EventCreate,
    TicketCreate,
    TicketDetail,
    TicketPatch,
    TicketSummary,
)

router = APIRouter(prefix="/api")


@router.get("/meta")
def meta():
    return {
        "agents": AGENTS,
        "categories": CATEGORIES,
        "priorities": [
            {"id": p, "hours": SLA_HOURS[p]} for p in PRIORITIES
        ],
        "statuses": STATUSES,
        "me": AGENTS_DEFAULT_ME,
    }


@router.get("/tickets", response_model=list[TicketSummary])
def list_tickets(
    view: str = Query("all", pattern="^(all|mine|unassigned|breach|done)$"),
    track: str | None = Query(None, pattern="^(saas|it)$"),
    q: str | None = None,
    db: Session = Depends(get_db),
):
    return services.list_tickets(db, view, track, q)


@router.post("/tickets", response_model=TicketDetail, status_code=201)
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db)):
    if payload.category not in CATEGORIES[payload.track]:
        raise HTTPException(422, f"'{payload.category}' is not a {payload.track} topic")
    t = Ticket(ref=services.next_ref(db), **payload.model_dump())
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.get("/tickets/{ref}", response_model=TicketDetail)
def get_ticket(ref: str, db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t:
        raise HTTPException(404, f"No ticket {ref}")
    return t


@router.patch("/tickets/{ref}", response_model=TicketDetail)
def patch_ticket(ref: str, payload: TicketPatch, db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t:
        raise HTTPException(404, f"No ticket {ref}")
    services.apply_patch(db, t, AGENTS_DEFAULT_ME, **payload.model_dump())
    db.commit()
    db.refresh(t)
    return t


@router.post("/tickets/{ref}/events", response_model=TicketDetail, status_code=201)
def add_event(ref: str, payload: EventCreate, db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t:
        raise HTTPException(404, f"No ticket {ref}")
    services.add_event(db, t, payload.actor or AGENTS_DEFAULT_ME, payload.kind, payload.body)
    db.commit()
    db.refresh(t)
    return t


# --- portal: no internal notes ever cross this line ---


@router.get("/portal/tickets", response_model=list[TicketDetail])
def portal_tickets(email: str, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Ticket).where(Ticket.email == email.lower().strip()).order_by(Ticket.created_at.desc())
    ).all()
    out = []
    for t in rows:
        d = TicketDetail.model_validate(t)
        d.events = [e for e in d.events if e.kind == "comment"]
        out.append(d)
    return out


@router.post("/portal/tickets/{ref}/events", response_model=TicketDetail, status_code=201)
def portal_reply(ref: str, payload: EventCreate, email: str, db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t or t.email != email.lower().strip():
        raise HTTPException(404, f"No ticket {ref} for that address")
    services.add_event(db, t, t.requester, "comment", payload.body)
    db.commit()
    db.refresh(t)
    d = TicketDetail.model_validate(t)
    d.events = [e for e in d.events if e.kind == "comment"]
    return d


@router.get("/counts")
def counts(db: Session = Depends(get_db)):
    return {"views": services.counts(db), "tracks": services.track_counts(db)}


@router.delete("/tickets/{ref}/events/{event_id}", response_model=TicketDetail)
def delete_event(ref: str, event_id: int, db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t:
        raise HTTPException(404, f"No ticket {ref}")
    ev, problem = services.delete_event(db, t, event_id, AGENTS_DEFAULT_ME)
    if problem:
        raise HTTPException(404 if ev is None and "No such" in problem else 403, problem)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/portal/tickets/{ref}/events/{event_id}", response_model=TicketDetail)
def portal_delete_event(ref: str, event_id: int, email: str, db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t or t.email != email.lower().strip():
        raise HTTPException(404, f"No ticket {ref} for that address")
    ev, problem = services.delete_event(db, t, event_id, t.requester, as_requester=True)
    if problem:
        raise HTTPException(404 if ev is None and "No such" in problem else 403, problem)
    db.commit()
    db.refresh(t)
    d = TicketDetail.model_validate(t)
    d.events = [e for e in d.events if e.kind == "comment"]
    return d


@router.delete("/tickets/{ref}/events/{event_id}", response_model=TicketDetail)
def delete_event(ref: str, event_id: int, db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t:
        raise HTTPException(404, f"No ticket {ref}")
    ev, problem = services.delete_event(db, t, event_id, AGENTS_DEFAULT_ME)
    if problem:
        raise HTTPException(404 if ev is None and "No such" in problem else 403, problem)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/portal/tickets/{ref}/events/{event_id}", response_model=TicketDetail)
def portal_delete_event(ref: str, event_id: int, email: str, db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t or t.email != email.lower().strip():
        raise HTTPException(404, f"No ticket {ref} for that address")
    ev, problem = services.delete_event(db, t, event_id, t.requester, as_requester=True)
    if problem:
        raise HTTPException(404 if ev is None and "No such" in problem else 403, problem)
    db.commit()
    db.refresh(t)
    d = TicketDetail.model_validate(t)
    d.events = [e for e in d.events if e.kind == "comment"]
    return d
